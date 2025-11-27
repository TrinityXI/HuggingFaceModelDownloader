# HuggingFace Downloader Monitor

A modern monitoring dashboard for the HuggingFace dataset downloader system, built with Next.js (frontend) and Flask (backend API).

## Features

- **Real-time Dashboard**: Monitor download queue status, completed tasks, and failures
- **Task Management**: View, retry, and delete tasks from the web interface
- **Activity Timeline**: Visualize daily task creation and completion trends
- **Status Filtering**: Filter tasks by status (pending, downloading, completed, failed)
- **Pagination**: Handle large numbers of tasks efficiently
- **Auto-refresh**: Dashboard automatically updates every 10 seconds

## Architecture

### Backend (Flask API)
- **Port**: 8080
- **Technology**: Python Flask with Flask-CORS
- **Database**: MySQL for queue data, RabbitMQ for queue stats
- **Endpoints**:
  - `GET /api/health` - Health check
  - `GET /api/stats/overview` - Overview statistics
  - `GET /api/queue/list` - List tasks with pagination and filtering
  - `GET /api/queue/<id>` - Get task details with event history
  - `GET /api/stats/timeline` - Timeline data for charts
  - `POST /api/queue/<id>/retry` - Retry a failed task
  - `DELETE /api/queue/<id>` - Delete a task

### Frontend (Next.js)
- **Port**: 3000
- **Technology**: Next.js 14, React, TypeScript, Tailwind CSS
- **Components**:
  - StatsOverview: Display key metrics
  - QueueList: Task table with actions
  - TimelineChart: Activity visualization using Recharts

## Setup

### Using Docker Compose (Recommended)

```bash
# Build and start all services including monitor
docker-compose up -d

# Access the UI
# Open http://localhost:3000 in your browser
```

### Manual Setup

#### Backend API

```bash
cd monitor
pip install -r requirements.txt

# Set environment variables
export MYSQL_HOST=localhost
export MYSQL_PORT=3306
export MYSQL_USER=hfuser
export MYSQL_PASSWORD=hfpassword
export MYSQL_DATABASE=hf_datasets
export RABBITMQ_HOST=localhost
export RABBITMQ_USER=admin
export RABBITMQ_PASSWORD=password123

# Run the API
python api_service.py
```

#### Frontend UI

```bash
cd monitor/ui
npm install

# Create .env.local
cp .env.local.example .env.local
# Edit .env.local and set NEXT_PUBLIC_API_URL=http://localhost:8080/api

# Development
npm run dev

# Production build
npm run build
npm start
```

## Environment Variables

### Backend API
- `MYSQL_HOST`: MySQL hostname (default: localhost)
- `MYSQL_PORT`: MySQL port (default: 3306)
- `MYSQL_USER`: MySQL username (default: root)
- `MYSQL_PASSWORD`: MySQL password
- `MYSQL_DATABASE`: MySQL database name (default: hf_datasets)
- `RABBITMQ_HOST`: RabbitMQ hostname (default: localhost)
- `RABBITMQ_PORT`: RabbitMQ port (default: 5672)
- `RABBITMQ_USER`: RabbitMQ username (default: admin)
- `RABBITMQ_PASSWORD`: RabbitMQ password
- `MONITOR_HOST`: API bind host (default: 0.0.0.0)
- `MONITOR_PORT`: API bind port (default: 8080)

### Frontend UI
- `NEXT_PUBLIC_API_URL`: Backend API URL (default: http://localhost:8080/api)

## API Usage Examples

### Get Overview Stats
```bash
curl http://localhost:8080/api/stats/overview
```

### List Tasks (with pagination and filtering)
```bash
# All tasks, page 1
curl http://localhost:8080/api/queue/list?page=1&per_page=20

# Failed tasks only
curl http://localhost:8080/api/queue/list?status=failed
```

### Retry a Failed Task
```bash
curl -X POST http://localhost:8080/api/queue/123/retry
```

### Delete a Task
```bash
curl -X DELETE http://localhost:8080/api/queue/123
```

## Development

### Backend Development
The Flask API uses hot-reload in development mode. Just modify the code and Flask will automatically restart.

### Frontend Development
Next.js provides hot module replacement (HMR):
```bash
cd monitor/ui
npm run dev
```
Visit http://localhost:3000 to see changes in real-time.

## Troubleshooting

### CORS Issues
If the frontend can't connect to the backend, ensure:
1. Flask-CORS is installed: `pip install flask-cors`
2. The API is accessible from the frontend's network
3. `NEXT_PUBLIC_API_URL` points to the correct API endpoint

### Database Connection Issues
Check that MySQL is running and accessible:
```bash
docker exec hf_mysql mysql -uhfuser -p<password> hf_datasets -e "SHOW TABLES;"
```

### Build Issues
If Next.js build fails, try:
```bash
cd monitor/ui
rm -rf .next node_modules
npm install
npm run build
```

## License
Same as the main project.
