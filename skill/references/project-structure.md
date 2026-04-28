# Project Structure Template

Standard layout for full-stack apps. For simple apps without a backend, flatten to just the frontend structure.

```
{project-name}/
+-- README.md                    # Generated documentation
+-- report.md                    # Build/fix history
+-- frontend/
|   +-- package.json
|   +-- public/
|   |   +-- index.html
|   +-- src/
|       +-- App.jsx              # Root component
|       +-- index.js             # Entry point
|       +-- components/          # Reusable UI components
|       +-- pages/               # Route-level components
|       +-- services/            # API client functions
|       +-- styles/              # CSS/styling
+-- backend/
|   +-- requirements.txt         # or package.json
|   +-- app.py                   # Entry point
|   +-- routes/                  # API route handlers
|   +-- models/                  # Data models
|   +-- services/                # Business logic
|   +-- database/                # DB setup, migrations
+-- tests/
|   +-- api/                     # API test scripts
|   +-- e2e/                     # VLA test definitions
+-- deploy/
    +-- start.sh                 # One-command startup script
    +-- docker-compose.yml       # If applicable
```
