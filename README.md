# HuggingFace Model Downloader

A comprehensive solution for managing and downloading Hugging Face models and datasets, featuring a Go-based CLI downloader, a Python backend service with queue management, and a Next.js web interface.

## Project Structure

- **`backend/`**: Python Flask service handling:
    - Scanning Hugging Face for new datasets.
    - Managing download queues (MySQL/RabbitMQ).
    - Serving a REST API.
    - Sending notifications (Feishu).
- **`frontend/`** (located in `monitor/ui`): Next.js web application for monitoring tasks and managing the queue.
- **`go_cli/`**: Go-based CLI tool for high-performance downloading.
- **`deploy/`**: Docker Compose and Dockerfiles for deployment.

## Prerequisites

- Docker & Docker Compose
- Go 1.20+ (for CLI)

## Getting Started

### 1. Start the Services (Backend & Frontend)

You can use the provided helper scripts to start the full stack (MySQL, Redis, RabbitMQ, Backend, Frontend):

**Linux/macOS:**
```bash
./start.sh
```

**Windows:**
```bat
start.bat
```

Or manually:
```bash
cd deploy
docker-compose up -d --build
```

- **Frontend UI**: [http://localhost:3000](http://localhost:3000)
- **Backend API**: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)

### 2. Configuration

Environment variables are defined in `deploy/docker-compose.yml`. Key variables include:

- `HF_TOKEN`: Your Hugging Face API Token.
- `PRODUCER_INTERVAL`: Scan interval in seconds (default: 3600).
- `FEISHU_WEBHOOK_URL`: (Optional) Feishu bot webhook for notifications.

### 3. CLI Downloader

The Go CLI tool is located in `go_cli/`.

**Build:**
```bash
cd go_cli
go build -o hfdownloader
```

**Usage:**
```bash
./hfdownloader -m <model_id>
```

## Architecture

The system uses a **Clean Architecture** approach for the backend:

- **API Layer**: `backend/app/api` - REST endpoints (Flask-RESTX).
- **Service Layer**: `backend/app/services` - Business logic (Scanner, Queue, RabbitMQ).
- **CRUD Layer**: `backend/app/crud` - Database operations.
- **Core**: `backend/app/core` - Configuration and utilities.

## License

MIT