# SQL Lineage Visualizer

A minimalist, high-performance developer tool that parses SQL queries and generates interactive, GPU-accelerated **table-level** and **column-level** lineage diagrams directly in your browser. 

Designed for data engineers, analytics engineers, and database administrators to easily trace data flow, verify relationships, and document complex queries.

---

## ⚡ Key Features

1. **Interactive Column-Level Lineage**: Click on any column within any node to trace its exact upstream inputs and downstream outputs.
2. **Focus Highlighting & Dimming**: Selecting a table or a column dims unrelated paths, highlighting only the relevant lineage path. Column tracing renders glowing gold dashed paths on the canvas.
3. **Multi-Dialect Parser Switcher**: Parse SQL queries using database-specific syntax dialects. Supports **Snowflake**, **BigQuery**, **PostgreSQL**, **Spark SQL**, **Redshift**, **MySQL**, and **SQLite**.
4. **Code Editor with Syntax Highlighting**: Includes a fully-functional, client-side SQL code editor powered by **CodeJar** and **PrismJS** with syntax coloring.
5. **Query History & Saved Snippets**:
   - **History**: Automatically logs your last 10 executed queries in chronological order.
   - **Saved**: Bookmark your favorite SQL snippets with custom labels using local browser storage (`localStorage`).
6. **Canvas Image Exporting**: Download a high-resolution PNG image of your lineage canvas with a single click for documentation or PR reviews.
7. **Ultra-Dark Mode Palette**: Clean dashboard theme designed around `#0B0F19` with glowing status nodes, color-coded table types, and crawling SVG edges.

---

## 🛠️ Tech Stack

- **Backend**: Python 3, FastAPI, Uvicorn, Sqlglot (pure Python AST parser), Pydantic
- **Frontend**: React (v18), React Flow / @xyflow/react (v12), Tailwind CSS, PrismJS, CodeJar, html2canvas (all loaded dynamically via ESM / CDN for zero-build, zero-npm footprint)

---

## 📂 Project Structure

The project is structured as a unified ASGI package:

```
sql-lineage-visualizer/
├── backend/
│   ├── main.py             # FastAPI backend with sqlglot parser and root HTML route
│   ├── index.html          # HTML shell containing the React & React Flow app via ESM
│   └── requirements.txt    # Python dependencies
├── .gitignore              # Standard git ignore definitions
└── README.md               # Documentation and setup instructions
```

---

## 🚀 Setup & Installation

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/sql-lineage-visualizer.git
cd sql-lineage-visualizer
```

### 2. Setup Virtual Environment
Create a virtual environment inside the `backend/` directory and install the requirements:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies (supports Python 3.10 through 3.14+)
pip install -r requirements.txt
```

*(Note: If compiling `pydantic-core` fails on unreleased Python versions like Python 3.14, run: `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 pip install -r requirements.txt`)*

### 3. Launch the Application
Run the FastAPI ASGI server using Uvicorn:

```bash
uvicorn main:app --reload --port 8000
```

### 4. Open in Browser
Navigate to **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)** in your browser.

---

## 🌐 Hosting & Deployment

This project is configured to be hosted as a decoupled system: **Render** (for the FastAPI Python backend) and **Netlify** (for the zero-build static React/React Flow frontend).

### 1. Deploy the Backend on Render
We have included a `render.yaml` Blueprint spec file to automate the deployment process:
1. Log into [Render](https://render.com/).
2. Click **New +** and select **Blueprint**.
3. Connect your GitHub repository.
4. Render will automatically parse the `render.yaml` file and create a Web Service named `sql-lineage-backend`.
5. Once deployed, note down your Render Web Service URL (e.g., `https://sql-lineage-backend.onrender.com`).

*Note: Render's Free instance spins down after 15 minutes of inactivity. When it is spun down, the first API request will experience a cold-start delay of ~50 seconds.*

### 2. Deploy the Frontend on Netlify
We have included a `netlify.toml` file to configure Netlify to publish the `backend/` directory directly:
1. Log into [Netlify](https://www.netlify.com/).
2. Click **Add new site** and select **Import from Git**.
3. Select your GitHub repository.
4. Netlify will automatically discover the `netlify.toml` settings:
   - **Publish directory:** `backend`
   - **Build command:** (Leave empty/default)
5. Deploy the site!

### 3. Connect Frontend and Backend
You have two options to connect your Netlify frontend to the Render backend:

#### Option A: Settings Tab in UI (No code changes required)
1. Open your Netlify-deployed URL.
2. Go to the **Settings** tab in the sidebar.
3. Paste your Render backend URL into the **Backend API URL** field and click **Save Settings**.
4. Click **Test Connection** to verify connection status. The app will persist this URL in your browser's local storage.

#### Option B: Proxy Rewrite (Best practice, avoids CORS issues)
1. Open the [netlify.toml](file:///Users/yashdantale/Documents/Projects/sql-lineage-visualizer/netlify.toml) file in your codebase.
2. Uncomment the `[[redirects]]` block at the bottom.
3. Replace `https://your-sql-lineage-backend.onrender.com` with your actual Render URL.
4. Commit and push the changes to GitHub. Netlify will redeploy, and all requests to `/api/*` will be proxied automatically.

---

## 📝 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---
Developed with 💜 by **Yash Dantale**

