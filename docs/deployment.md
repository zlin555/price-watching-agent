# Deployment Notes

## Recommended Architecture

- Frontend: Vercel static site.
- Backend: Hugging Face Space with Docker, running FastAPI on port `7860`.
- Database: Aiven for PostgreSQL with `pgvector`.
- Scheduler: backend in-process loop for demo; production should add an external cron trigger or a dedicated worker.

## Aiven PostgreSQL

Use PostgreSQL instead of a separate vector database for this project. The app needs normal relational data and vector similarity search, and Aiven PostgreSQL supports `pgvector`.

1. Create an Aiven for PostgreSQL service.
2. Copy the service URI.
3. Connect with `psql`.
4. Run:

```sql
CREATE EXTENSION vector;
```

5. Apply `backend/schema.sql`.

Example:

```powershell
psql "postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require" -f backend/schema.sql
```

## Hugging Face Space

1. Create a new Space.
2. Choose Docker as the SDK.
3. Push this repo or the backend folder with the root `Dockerfile`.
4. Set Space secrets:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
APP_ENV=production
```

5. The Dockerfile runs:

```text
uvicorn backend.app:app --host 0.0.0.0 --port 7860
```

## Vercel Frontend

After the backend URL is live, configure the frontend API base URL. The current prototype still falls back to local demo data when the backend is unavailable.

Recommended next change:

```js
const API_BASE = window.PRICEPILOT_API_BASE || "https://YOUR-HF-SPACE.hf.space";
```

## Embeddings

Current backend uses a small deterministic text embedding prototype so the feature works without a large model.

Production options:

- Text first: `sentence-transformers/all-MiniLM-L6-v2`
- Image + text CLIP: `sentence-transformers/clip-ViT-B-32`
- OpenCLIP if you want local model control

Store generated vectors in:

- `users.profile_embedding`
- `discovered_products.embedding`

Then compare with cosine distance:

```sql
SELECT *
FROM discovered_products
ORDER BY embedding <=> $1
LIMIT 20;
```

