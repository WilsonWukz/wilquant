# wilquant

wilquant is a quantitative research platform for market data management, strategy evaluation and paper trading. Each run retains its data versions, strategy configuration and execution records.

## Capabilities

| Area | Features |
| --- | --- |
| Market data | CSV and Parquet imports, field mapping, quality checks, versioned datasets and trading calendars. |
| Backtesting | Versioned strategies, transaction costs, slippage, liquidity constraints, equity curves and performance metrics. Built-in strategies include buy-and-hold and momentum rotation. |
| Research | Experiment comparisons, diagnostics, reports and a research journal linked to the underlying runs. |
| Paper trading | Strategy-driven and manual orders, pre-trade risk checks, partial fills, positions, cash accounting and session recovery. |
| AI analysis | Two-stage diagnosis and recommendations with evidence references, time cutoffs and structured validation. Available through the API. |

Backtesting and paper trading share execution logic for fees, slippage and market rules. Published data and strategy versions remain fixed for each run.

Current market support is CN A-shares. Paper trading uses simulated capital; wilquant does not submit orders to a broker.

## Getting started

The supplied scripts target Windows 10/11 with PowerShell 5.1 or later. Install uv and Node.js 22 with npm. The backend requires Python 3.11–3.13.

Run these commands from the repository root:

```powershell
# Install dependencies
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1

# Apply database migrations
$env:QUANT_LAB_PROJECT_ROOT = (Get-Location).Path
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head

# Start the API and web application
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1
```

Open the [workspace](http://127.0.0.1:5173) or the [API reference](http://127.0.0.1:8000/docs). The web application has pages for data imports, datasets, market data, backtests, research and paper trading.

Stop the services:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1
```

## Configuration

Settings use the `QUANT_LAB_` prefix. See [.env.example](.env.example) for defaults; use a local `.env` file or environment variables for overrides.

Runtime data defaults to the project directory. Set `QUANT_LAB_RUNTIME_ROOT` before initialization and startup for a separate storage location. Changing this setting does not move existing data.

AI analysis is optional and disabled by default. It uses a separate Provider Host with an explicitly configured OpenAI-compatible endpoint. Provider credentials belong in Windows Credential Manager, not in repository files. See [Provider setup](docs/ai-3-provider-operations.md) and [Analysis API configuration](docs/ai-4-research-operations.md).

## Development

The application uses React and TypeScript, a FastAPI backend, SQLite for transactional state, and Parquet with DuckDB for market data. Alembic manages schema changes.

Run the full test and build checks:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1
```

This runs pytest, Ruff, mypy, Vitest, TypeScript checks and the Vite production build.

## Documentation

- [System architecture](ARCHITECTURE.md)
- [AI Provider setup](docs/ai-3-provider-operations.md)
- [Research analysis API](docs/ai-4-research-operations.md)
- [Design decisions and technical documentation](docs/)
