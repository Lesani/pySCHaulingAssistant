/**
 * SC Hauling Assistant - Mission Sync API
 *
 * Cloudflare Worker with D1 database for syncing mission scans.
 *
 * Deploy instructions:
 * 1. Create a Cloudflare account at https://dash.cloudflare.com
 * 2. Install Wrangler CLI: npm install -g wrangler
 * 3. Login: wrangler login
 * 4. Create D1 database: wrangler d1 create sc-hauling-db
 * 5. Update wrangler.toml with your database_id
 * 6. Initialize schema: wrangler d1 execute sc-hauling-db --file=schema.sql
 * 7. Deploy: wrangler deploy
 */

// CORS headers for cross-origin requests
const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-API-Key, Authorization',
};

// Discord OAuth2 configuration
const DISCORD_API_URL = 'https://discord.com/api/v10';
const SESSION_DURATION_DAYS = 60;

// Simple API key validation (set in wrangler.toml or dashboard)
function validateApiKey(request, env) {
  // If no API key is configured, allow all requests (open mode)
  if (!env.API_KEY) {
    return true;
  }
  const providedKey = request.headers.get('X-API-Key');
  return providedKey === env.API_KEY;
}

// JSON response helper
function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...CORS_HEADERS,
    },
  });
}

// Error response helper
function errorResponse(message, status = 400) {
  return jsonResponse({ error: message, success: false }, status);
}

// Generate a cryptographically secure session token
function generateSessionToken() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array, byte => byte.toString(16).padStart(2, '0')).join('');
}

// Validate session token and return user info
async function validateSession(request, env) {
  const authHeader = request.headers.get('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return null;
  }

  const token = authHeader.substring(7);

  // Look up session and join with user
  const result = await env.DB.prepare(`
    SELECT s.token, s.discord_id, s.expires_at, u.username, u.avatar
    FROM sessions s
    JOIN users u ON s.discord_id = u.discord_id
    WHERE s.token = ?
  `).bind(token).first();

  if (!result) {
    return null;
  }

  // Check if session is expired
  if (new Date(result.expires_at) < new Date()) {
    // Clean up expired session
    await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
    return null;
  }

  return {
    discord_id: result.discord_id,
    username: result.username,
    avatar: result.avatar,
  };
}

// Exchange Discord authorization code for tokens
async function exchangeDiscordCode(code, redirectUri, env) {
  const response = await fetch(`${DISCORD_API_URL}/oauth2/token`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams({
      client_id: env.DISCORD_CLIENT_ID,
      client_secret: env.DISCORD_CLIENT_SECRET,
      grant_type: 'authorization_code',
      code: code,
      redirect_uri: redirectUri,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Discord token exchange failed: ${error}`);
  }

  return await response.json();
}

// Fetch Discord user info
async function fetchDiscordUser(accessToken) {
  const response = await fetch(`${DISCORD_API_URL}/users/@me`, {
    headers: {
      'Authorization': `Bearer ${accessToken}`,
    },
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Discord user fetch failed: ${error}`);
  }

  return await response.json();
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    // Validate API key for non-GET requests (or all if configured)
    if (request.method !== 'GET' && !validateApiKey(request, env)) {
      return errorResponse('Invalid API key', 401);
    }

    try {
      // Route requests - Public endpoints
      if (path === '/api/health') {
        return jsonResponse({ status: 'ok', timestamp: new Date().toISOString() });
      }

      if (path === '/api/stats') {
        return await getStats(env);
      }

      // Auth endpoints
      if (path === '/api/auth/discord/callback' && request.method === 'POST') {
        return await handleDiscordCallback(request, env);
      }

      if (path === '/api/auth/me' && request.method === 'GET') {
        return await handleGetMe(request, env);
      }

      if (path === '/api/auth/logout' && request.method === 'POST') {
        return await handleLogout(request, env);
      }

      // Protected endpoints - require authentication
      if (path === '/api/scans' && request.method === 'GET') {
        const user = await validateSession(request, env);
        if (!user) {
          return errorResponse('Authentication required', 401);
        }
        return await getScans(request, env);
      }

      if (path === '/api/scans' && request.method === 'POST') {
        const user = await validateSession(request, env);
        if (!user) {
          return errorResponse('Authentication required', 401);
        }
        return await uploadScans(request, env, user);
      }

      if (path === '/api/sync' && request.method === 'POST') {
        const user = await validateSession(request, env);
        if (!user) {
          return errorResponse('Authentication required', 401);
        }
        return await syncScans(request, env, user);
      }

      return errorResponse('Not found', 404);

    } catch (error) {
      console.error('Error:', error);
      return errorResponse(`Server error: ${error.message}`, 500);
    }
  },
};

/**
 * GET /api/scans - Retrieve scans with optional filters
 * Query params:
 *   - since: ISO timestamp to get scans after
 *   - location: filter by scan location (matches any in the array)
 *   - limit: max results (default 100, max 1000)
 */
async function getScans(request, env) {
  const url = new URL(request.url);
  const since = url.searchParams.get('since');
  const location = url.searchParams.get('location');
  const limit = Math.min(parseInt(url.searchParams.get('limit') || '100'), 1000);

  let query = 'SELECT * FROM scans WHERE 1=1';
  const params = [];

  if (since) {
    query += ' AND uploaded_at > ?';
    params.push(since);
  }

  if (location) {
    // Use JSON functions to check if location is in the array
    query += ' AND (scan_locations LIKE ? OR scan_locations LIKE ? OR scan_locations LIKE ?)';
    // Match: ["location", or ,"location", or ,"location"]
    params.push(`["%${location}%`);
    params.push(`%,"${location}",%`);
    params.push(`%,"${location}"]`);
  }

  query += ' ORDER BY uploaded_at DESC LIMIT ?';
  params.push(limit);

  const stmt = env.DB.prepare(query);
  const { results } = await stmt.bind(...params).all();

  // Parse JSON fields for each result
  const scans = results.map(row => ({
    ...row,
    scan_locations: JSON.parse(row.scan_locations || '[]'),
    objectives: JSON.parse(row.objectives || '[]'),
  }));

  return jsonResponse({
    success: true,
    count: scans.length,
    scans,
  });
}

/**
 * Helper to normalize scan locations to array format
 * Accepts either scan_locations (array) or scan_location (string) for backward compat
 */
function normalizeScanLocations(scan) {
  // Prefer scan_locations array
  if (Array.isArray(scan.scan_locations)) {
    return scan.scan_locations;
  }
  // Fallback to single scan_location
  if (scan.scan_location) {
    return [scan.scan_location];
  }
  return [];
}

/**
 * POST /api/scans - Upload new scans
 * Body: { scans: [...] }
 * Requires authentication - user is passed from session validation
 */
async function uploadScans(request, env, user) {
  const body = await request.json();
  const scans = body.scans || [];

  if (!Array.isArray(scans) || scans.length === 0) {
    return errorResponse('No scans provided');
  }

  if (scans.length > 100) {
    return errorResponse('Maximum 100 scans per request');
  }

  // Use authenticated username instead of body parameter
  const uploadedBy = user.username;
  const uploadedAt = new Date().toISOString();

  let inserted = 0;
  let duplicates = 0;

  for (const scan of scans) {
    try {
      // Check for duplicate by ID
      const existing = await env.DB.prepare(
        'SELECT id FROM scans WHERE id = ?'
      ).bind(scan.id).first();

      if (existing) {
        duplicates++;
        continue;
      }

      // Normalize locations to array
      const locations = normalizeScanLocations(scan);

      // Insert new scan
      await env.DB.prepare(`
        INSERT INTO scans (
          id, scan_timestamp, scan_locations, reward, availability,
          rank, contracted_by, objectives, uploaded_by, uploaded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        scan.id,
        scan.scan_timestamp,
        JSON.stringify(locations),
        scan.mission_data?.reward || scan.reward || 0,
        scan.mission_data?.availability || scan.availability || '',
        scan.mission_data?.rank || scan.rank || '',
        scan.mission_data?.contracted_by || scan.contracted_by || '',
        JSON.stringify(scan.mission_data?.objectives || scan.objectives || []),
        uploadedBy,
        uploadedAt
      ).run();

      inserted++;
    } catch (err) {
      console.error(`Error inserting scan ${scan.id}:`, err);
    }
  }

  return jsonResponse({
    success: true,
    inserted,
    duplicates,
    message: `Uploaded ${inserted} new scans, ${duplicates} duplicates skipped`,
  });
}

/**
 * POST /api/sync - Two-way sync
 * Body: { scans: [...], last_sync: "ISO timestamp" }
 * Returns: { uploaded: n, downloaded: [...] }
 * Requires authentication - user is passed from session validation
 */
async function syncScans(request, env, user) {
  const body = await request.json();
  const localScans = body.scans || [];
  const lastSync = body.last_sync || '1970-01-01T00:00:00Z';
  // Use authenticated username instead of body parameter
  const uploadedBy = user.username;
  const uploadedAt = new Date().toISOString();

  // Upload local scans
  let inserted = 0;
  let updated = 0;
  let duplicates = 0;

  for (const scan of localScans) {
    try {
      const existing = await env.DB.prepare(
        'SELECT id, scan_locations FROM scans WHERE id = ?'
      ).bind(scan.id).first();

      // Normalize locations to array
      const newLocations = normalizeScanLocations(scan);
      const newLocationsJson = JSON.stringify(newLocations);

      if (existing) {
        // Check if scan_locations has changed and needs updating
        if (existing.scan_locations !== newLocationsJson) {
          await env.DB.prepare(
            'UPDATE scans SET scan_locations = ? WHERE id = ?'
          ).bind(newLocationsJson, scan.id).run();
          updated++;
        } else {
          duplicates++;
        }
        continue;
      }

      await env.DB.prepare(`
        INSERT INTO scans (
          id, scan_timestamp, scan_locations, reward, availability,
          rank, contracted_by, objectives, uploaded_by, uploaded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        scan.id,
        scan.scan_timestamp,
        newLocationsJson,
        scan.mission_data?.reward || scan.reward || 0,
        scan.mission_data?.availability || scan.availability || '',
        scan.mission_data?.rank || scan.rank || '',
        scan.mission_data?.contracted_by || scan.contracted_by || '',
        JSON.stringify(scan.mission_data?.objectives || scan.objectives || []),
        uploadedBy,
        uploadedAt
      ).run();

      inserted++;
    } catch (err) {
      console.error(`Error inserting scan ${scan.id}:`, err);
    }
  }

  // Get scans uploaded since last sync (excluding ones we just uploaded)
  const localIdSet = new Set(localScans.map(s => s.id));

  // Fetch scans without excluding in SQL to avoid "too many SQL variables" error
  // Filter out local scans in JavaScript instead
  const query = 'SELECT * FROM scans WHERE uploaded_at > ? ORDER BY uploaded_at DESC LIMIT 1000';
  const stmt = env.DB.prepare(query);
  const { results: allResults } = await stmt.bind(lastSync).all();

  // Filter out scans the client already has
  const results = allResults.filter(row => !localIdSet.has(row.id)).slice(0, 500);

  const newScans = results.map(row => ({
    id: row.id,
    scan_timestamp: row.scan_timestamp,
    scan_locations: JSON.parse(row.scan_locations || '[]'),
    mission_data: {
      reward: row.reward,
      availability: row.availability,
      rank: row.rank,
      contracted_by: row.contracted_by,
      objectives: JSON.parse(row.objectives || '[]'),
    },
    uploaded_by: row.uploaded_by,
    uploaded_at: row.uploaded_at,
  }));

  return jsonResponse({
    success: true,
    uploaded: inserted,
    updated,
    duplicates,
    downloaded: newScans,
    sync_timestamp: uploadedAt,
  });
}

/**
 * GET /api/stats - Get database statistics
 */
async function getStats(env) {
  const totalResult = await env.DB.prepare(
    'SELECT COUNT(*) as total FROM scans'
  ).first();

  const recentResult = await env.DB.prepare(`
    SELECT COUNT(*) as count
    FROM scans
    WHERE uploaded_at > datetime('now', '-24 hours')
  `).first();

  // Count scans with/without locations
  const withLocationsResult = await env.DB.prepare(`
    SELECT COUNT(*) as count
    FROM scans
    WHERE scan_locations IS NOT NULL AND scan_locations != '[]'
  `).first();

  return jsonResponse({
    success: true,
    stats: {
      total_scans: totalResult?.total || 0,
      scans_last_24h: recentResult?.count || 0,
      scans_with_locations: withLocationsResult?.count || 0,
    },
  });
}

/**
 * POST /api/auth/discord/callback - Exchange Discord auth code for session token
 * Body: { code: "...", redirect_uri: "..." }
 */
async function handleDiscordCallback(request, env) {
  const body = await request.json();
  const { code, redirect_uri } = body;

  if (!code || !redirect_uri) {
    return errorResponse('Missing code or redirect_uri');
  }

  // Check if Discord credentials are configured
  if (!env.DISCORD_CLIENT_ID || !env.DISCORD_CLIENT_SECRET) {
    return errorResponse('Discord OAuth not configured on server', 500);
  }

  // Exchange code for Discord tokens
  const tokens = await exchangeDiscordCode(code, redirect_uri, env);

  // Fetch Discord user info
  const discordUser = await fetchDiscordUser(tokens.access_token);

  const now = new Date().toISOString();
  const expiresAt = new Date(Date.now() + SESSION_DURATION_DAYS * 24 * 60 * 60 * 1000).toISOString();

  // Upsert user in database
  await env.DB.prepare(`
    INSERT INTO users (discord_id, username, avatar, created_at, last_login)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(discord_id) DO UPDATE SET
      username = excluded.username,
      avatar = excluded.avatar,
      last_login = excluded.last_login
  `).bind(
    discordUser.id,
    discordUser.username,
    discordUser.avatar || null,
    now,
    now
  ).run();

  // Generate session token
  const sessionToken = generateSessionToken();

  // Store session
  await env.DB.prepare(`
    INSERT INTO sessions (token, discord_id, created_at, expires_at)
    VALUES (?, ?, ?, ?)
  `).bind(sessionToken, discordUser.id, now, expiresAt).run();

  return jsonResponse({
    success: true,
    session_token: sessionToken,
    expires_at: expiresAt,
    user: {
      discord_id: discordUser.id,
      username: discordUser.username,
      avatar: discordUser.avatar,
    },
  });
}

/**
 * GET /api/auth/me - Get current authenticated user info
 */
async function handleGetMe(request, env) {
  const user = await validateSession(request, env);

  if (!user) {
    return errorResponse('Not authenticated', 401);
  }

  return jsonResponse({
    success: true,
    user: {
      discord_id: user.discord_id,
      username: user.username,
      avatar: user.avatar,
    },
  });
}

/**
 * POST /api/auth/logout - Invalidate session
 */
async function handleLogout(request, env) {
  const authHeader = request.headers.get('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return errorResponse('No session token provided', 400);
  }

  const token = authHeader.substring(7);

  // Delete the session
  await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();

  return jsonResponse({
    success: true,
    message: 'Logged out successfully',
  });
}
