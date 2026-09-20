

# Bazaar Marketplace

Full-stack buy-and-sell marketplace with buyer, seller, and admin experiences.

## Project

The application is in the [`marketplace`](./marketplace) directory.

## Live Demo

Visit the deployed marketplace at [bazaar-marketplace-nate.fly.dev](https://bazaar-marketplace-nate.fly.dev/).

## Run Locally

```powershell
cd marketplace/backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

See [`marketplace/README.md`](./marketplace/README.md) for API endpoints, administrator setup, and feature details.
