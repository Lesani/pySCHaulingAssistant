# SC Hauling Assistant - Cloud Sync API

This folder contains a Cloudflare Worker that provides a REST API for syncing mission scans between users.

## Features

- **Two-way sync**: Upload your scans, download scans from others
- **SQLite database**: Uses Cloudflare D1 (free tier: 500MB storage)
- **Location filtering**: Query scans by in-game location
- **Optional authentication**: Protect uploads with an API key
- **Fast global access**: Runs on Cloudflare's edge network

## Free Tier Limits

| Resource | Free Limit |
|----------|------------|
| D1 Storage | 500 MB |
| D1 Reads | 5 million rows/day |
| D1 Writes | 100,000 rows/day |
| Worker Requests | 100,000/day |

This is plenty for sharing mission scans with friends!

## Deployment Instructions

### 1. Prerequisites

- [Node.js](https://nodejs.org/) installed
- [Cloudflare account](https://dash.cloudflare.com/sign-up) (free)

### 2. Install Wrangler CLI

```bash
npm install -g wrangler
```

### 3. Login to Cloudflare

```bash
wrangler login
```

This opens a browser to authenticate.

### 4. Create the D1 Database

```bash
cd cloudflare-worker
wrangler d1 create sc-hauling-db
```

Copy the `database_id` from the output - you'll need it next.

### 5. Update Configuration

Edit `wrangler.toml` and replace `YOUR_DATABASE_ID_HERE` with your actual database ID:

```toml
[[d1_databases]]
binding = "DB"
database_name = "sc-hauling-db"
database_id = "abc123-your-actual-id-here"
```

### 6. Initialize the Database Schema

```bash
wrangler d1 execute sc-hauling-db --file=schema.sql
```

### 7. Deploy the Worker

```bash
wrangler deploy
```

You'll get a URL like: `https://sc-hauling-sync.your-subdomain.workers.dev`

### 8. Configure the App

In the SC Hauling Assistant app:
1. Go to **Configuration** tab
2. Scroll to **Cloud Sync Settings**
3. Enter your Worker URL in **Sync API URL**
4. Click **Test Connection** to verify
5. Click **Save Configuration**

## Optional: Add API Key Protection

To require authentication for uploads:

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Navigate to: Workers & Pages > sc-hauling-sync > Settings > Variables
3. Add a variable:
   - Name: `API_KEY`
   - Value: (your secret key)
4. Click Save

Then in the app's Configuration tab, enter the same API key.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/stats` | GET | Database statistics |
| `/api/scans` | GET | Download scans (with filters) |
| `/api/scans` | POST | Upload new scans |
| `/api/sync` | POST | Two-way sync |

### Query Parameters for GET /api/scans

- `since` - ISO timestamp to get scans after
- `location` - Filter by scan location
- `limit` - Max results (default 100, max 1000)

### Example: Get recent scans at Baijini Point

```
GET /api/scans?location=Baijini%20Point&limit=50
```

## Troubleshooting

### "Connection Failed" error

1. Check the URL is correct (should start with `https://`)
2. Verify the Worker is deployed: `wrangler deployments list`
3. Check Cloudflare dashboard for errors

### "Invalid API key" error

- Make sure the API key in the app matches the one in Cloudflare dashboard
- API key is case-sensitive

### Database issues

Re-initialize the schema:
```bash
wrangler d1 execute sc-hauling-db --file=schema.sql
```

View database contents:
```bash
wrangler d1 execute sc-hauling-db --command="SELECT COUNT(*) FROM scans"
```

## Local Development

Test locally before deploying:

```bash
wrangler dev
```

This starts a local server at `http://localhost:8787`.
