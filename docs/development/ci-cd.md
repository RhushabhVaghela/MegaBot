# CI/CD Guide

This guide covers the continuous integration and deployment pipelines for MegaBot, ensuring reliable, automated testing, building, and deployment.

## CI/CD Overview

MegaBot uses GitHub Actions for continuous integration and deployment with the following stages:

- **Code Quality**: Linting, type checking, security scanning
- **Testing**: Unit, integration, security, and performance tests
- **Building**: Docker image creation and artifact generation
- **Deployment**: Automated deployment to staging and production
- **Monitoring**: Post-deployment health checks and alerting

## GitHub Actions Workflows

### Main CI Pipeline (`.github/workflows/ci.yml`)

```yaml
name: CI
on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  quality:
    name: Code Quality
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Cache dependencies
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements*.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Lint with flake8
        run: flake8 megabot/ --count --select=E9,F63,F7,F82 --show-source --statistics

      - name: Check black formatting
        run: black --check megabot/

      - name: Type check with mypy
        run: mypy megabot/ --ignore-missing-imports

      - name: Security scan with bandit
        run: bandit -r megabot/ -f json -o security-report.json

      - name: Upload security report
        uses: actions/upload-artifact@v3
        with:
          name: security-report
          path: security-report.json

  test:
    name: Tests
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt

      - name: Run unit tests
        run: pytest tests/unit/ -v --tb=short --cov=megabot --cov-report=xml

      - name: Run integration tests
        run: pytest tests/integration/ -v --tb=short
        env:
          DATABASE_URL: postgresql://postgres:test_password@localhost:5432/test

      - name: Run security tests
        run: pytest tests/security/ -v --tb=short

      - name: Upload coverage reports
        uses: actions/upload-artifact@v3
        with:
          name: coverage-${{ matrix.python-version }}
          path: coverage.xml

  build:
    name: Build
    needs: [quality, test]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: actions/docker/setup-buildx-action@v3

      - name: Log in to Docker Hub
        uses: actions/docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}

      - name: Extract metadata
        id: meta
        uses: actions/docker/metadata-action@v5
        with:
          images: megabot/megabot
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=sha,prefix={{branch}}-
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Build and push Docker image
        uses: actions/docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Generate artifact attestation
        uses: actions/attest-build-provenance@v1
        with:
          subject-path: '/tmp/megabot.tar.gz'
```

### Security Scanning Pipeline (`.github/workflows/security.yml`)

```yaml
name: Security Scan
on:
  schedule:
    - cron: '0 0 * * 1'  # Weekly on Mondays
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  security:
    name: Security Scanning
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '.'
          format: 'sarif'
          output: 'trivy-results.sarif'

      - name: Run Snyk to check for vulnerabilities
        uses: snyk/actions/python@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
        with:
          args: --file=requirements.txt

      - name: Run dependency check
        uses: dependency-check/Dependency-Check_Action@main
        with:
          project: 'MegaBot'
          path: '.'
          format: 'ALL'

      - name: Upload Trivy scan results
        uses: github/codeql-action/upload-sarif@v2
        if: always()
        with:
          sarif_file: 'trivy-results.sarif'

      - name: Upload dependency check results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: dependency-check-report
          path: reports/
```

### Performance Testing Pipeline (`.github/workflows/performance.yml`)

```yaml
name: Performance Tests
on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:

jobs:
  performance:
    name: Performance Testing
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt

      - name: Run performance tests
        run: pytest tests/performance/ -v --tb=short --benchmark-json=benchmark.json

      - name: Store benchmark result
        uses: benchmark-action/github-action-benchmark@v1
        with:
          name: Python Benchmark
          tool: 'pytest'
          output-file-path: benchmark.json
          github-token: ${{ secrets.GITHUB_TOKEN }}
          auto-push: true

      - name: Run memory profiling
        run: |
          python -m memory_profiler megabot/core/orchestrator.py > memory_profile.txt

      - name: Upload performance artifacts
        uses: actions/upload-artifact@v3
        with:
          name: performance-results
          path: |
            benchmark.json
            memory_profile.txt
```

## Deployment Pipelines

### Staging Deployment (`.github/workflows/deploy-staging.yml`)

```yaml
name: Deploy to Staging
on:
  push:
    branches: [ develop ]

jobs:
  deploy:
    name: Deploy to Staging
    runs-on: ubuntu-latest
    environment: staging

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push to ECR
        run: |
          IMAGE_TAG=${{ github.sha }}
          REPOSITORY=${{ secrets.ECR_REPOSITORY }}

          docker build -t $REPOSITORY:$IMAGE_TAG .
          docker tag $REPOSITORY:$IMAGE_TAG $REPOSITORY:staging
          docker push $REPOSITORY:$IMAGE_TAG
          docker push $REPOSITORY:staging

      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster megabot-staging \
            --service megabot-service \
            --force-new-deployment \
            --region us-east-1

      - name: Wait for deployment
        run: |
          aws ecs wait services-stable \
            --cluster megabot-staging \
            --services megabot-service \
            --region us-east-1

      - name: Health check
        run: |
          ENDPOINT=$(aws ecs describe-services \
            --cluster megabot-staging \
            --services megabot-service \
            --region us-east-1 \
            --query 'services[0].taskDefinition' \
            --output text)

          # Wait for health endpoint to respond
          for i in {1..30}; do
            if curl -f http://$ENDPOINT/health; then
              echo "Health check passed"
              break
            fi
            sleep 10
          done

      - name: Run smoke tests
        run: |
          npm install -g artillery
          artillery run smoke-tests.yml --target http://$ENDPOINT

      - name: Notify deployment
        uses: 8398a7/action-slack@v3
        with:
          status: success
          text: 'MegaBot deployed to staging successfully'
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        if: success()

      - name: Notify failure
        uses: 8398a7/action-slack@v3
        with:
          status: failure
          text: 'MegaBot staging deployment failed'
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        if: failure()
```

### Production Deployment (`.github/workflows/deploy-production.yml`)

```yaml
name: Deploy to Production
on:
  release:
    types: [published]
  workflow_dispatch:
    inputs:
      version:
        description: 'Version to deploy'
        required: true

jobs:
  deploy:
    name: Deploy to Production
    runs-on: ubuntu-latest
    environment: production

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Determine image tag
        run: |
          if [ "${{ github.event.release.tag_name }}" ]; then
            echo "IMAGE_TAG=${{ github.event.release.tag_name }}" >> $GITHUB_ENV
          else
            echo "IMAGE_TAG=${{ github.event.inputs.version }}" >> $GITHUB_ENV
          fi

      - name: Pull and retag image
        run: |
          REPOSITORY=${{ secrets.ECR_REPOSITORY }}
          docker pull $REPOSITORY:$IMAGE_TAG
          docker tag $REPOSITORY:$IMAGE_TAG $REPOSITORY:production

      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster megabot-production \
            --service megabot-service \
            --force-new-deployment \
            --region us-east-1

      - name: Wait for deployment
        run: |
          aws ecs wait services-stable \
            --cluster megabot-production \
            --services megabot-service \
            --region us-east-1

      - name: Run production smoke tests
        run: |
          npm install -g artillery
          artillery run production-tests.yml --target ${{ secrets.PRODUCTION_URL }}

      - name: Create deployment record
        run: |
          aws dynamodb put-item \
            --table-name megabot-deployments \
            --item '{
              "version": {"S": "'$IMAGE_TAG'"},
              "timestamp": {"S": "'$(date -Iseconds)'"},
              "commit": {"S": "'$GITHUB_SHA'"},
              "status": {"S": "success"}
            }'

      - name: Notify deployment
        uses: 8398a7/action-slack@v3
        with:
          status: success
          text: 'MegaBot ${{ env.IMAGE_TAG }} deployed to production'
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        if: success()
```

## Infrastructure as Code

### Terraform Configuration

#### Main Infrastructure (`infrastructure/main.tf`)

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "megabot-terraform-state"
    key    = "infrastructure/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = "us-east-1"
}

# VPC Configuration
module "vpc" {
  source = "./modules/vpc"

  name = "megabot"
  cidr = "10.0.0.0/16"

  azs             = ["us-east-1a", "us-east-1b", "us-east-1c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true
}

# ECS Cluster
module "ecs" {
  source = "./modules/ecs"

  name = "megabot"

  container_insights = true

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

# ECR Repository
resource "aws_ecr_repository" "megabot" {
  name                 = "megabot"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# RDS Database
module "db" {
  source = "./modules/rds"

  identifier = "megabot"

  engine            = "postgres"
  engine_version    = "15.4"
  instance_class    = "db.t4g.micro"
  allocated_storage = 20

  db_name  = "megabot"
  username = "megabot"
  port     = "5432"

  vpc_security_group_ids = [module.security_groups.rds_sg_id]
  subnet_ids              = module.vpc.private_subnets

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"
}

# Application Load Balancer
module "alb" {
  source = "./modules/alb"

  name = "megabot"

  vpc_id          = module.vpc.vpc_id
  subnets         = module.vpc.public_subnets
  security_groups = [module.security_groups.alb_sg_id]

  target_groups = [
    {
      name             = "megabot"
      backend_protocol = "HTTP"
      backend_port     = 3000
      target_type      = "ip"
    }
  ]

  http_tcp_listeners = [
    {
      port               = 80
      protocol           = "HTTP"
      target_group_index = 0
    }
  ]
}

# ECS Service
module "ecs_service" {
  source = "./modules/ecs-service"

  name = "megabot"

  cluster_arn  = module.ecs.cluster_arn
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnets
  desired_count = 2

  container_definitions = jsonencode([
    {
      name  = "megabot"
      image = "${aws_ecr_repository.megabot.repository_url}:latest"

      portMappings = [
        {
          containerPort = 3000
          hostPort      = 3000
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "DATABASE_URL"
          value = "postgresql://${module.db.db_instance_username}:${module.db.db_instance_password}@${module.db.db_instance_endpoint}/${module.db.db_instance_name}"
        }
      ]

      secrets = [
        {
          name      = "ANTHROPIC_API_KEY"
          valueFrom = aws_secretsmanager_secret.anthropic_api_key.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/megabot"
          "awslogs-region"        = "us-east-1"
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
        interval = 30
        timeout = 5
        retries = 3
      }
    }
  ])

  load_balancer = {
    target_group_arn = module.alb.target_group_arns[0]
    container_name   = "megabot"
    container_port   = 3000
  }

  security_groups = [module.security_groups.ecs_sg_id]
}

# Secrets Manager
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name = "megabot/anthropic-api-key"
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = var.anthropic_api_key
}
```

### Docker Configuration

#### Multi-Stage Dockerfile (`Dockerfile`)

```dockerfile
# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# Production stage
FROM python:3.11-slim as production

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash megabot

WORKDIR /home/megabot

# Copy installed packages from builder
COPY --from=builder /root/.local /home/megabot/.local
ENV PATH=/home/megabot/.local/bin:$PATH

# Copy application code
COPY . .

# Change ownership
RUN chown -R megabot:megabot /home/megabot

# Switch to non-root user
USER megabot

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "megabot"]
```

#### Docker Compose for Development (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  megabot:
    build:
      context: .
      target: production
    ports:
      - "3000:3000"
      - "18789:18789"
      - "18790:18790"
    volumes:
      - ./mega-config.yaml:/home/megabot/mega-config.yaml
      - ./data:/home/megabot/data
      - ./logs:/home/megabot/logs
    environment:
      - PYTHONPATH=/home/megabot
    restart: unless-stopped
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: megabot
      POSTGRES_USER: megabot
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped

volumes:
  postgres_data:
```

## Monitoring and Observability

### Application Monitoring

#### Health Checks (`health.py`)

```python
from fastapi import APIRouter, Response
from core.orchestrator import orchestrator
import time

router = APIRouter()

@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "timestamp": time.time()}

@router.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with component status."""
    health = await orchestrator.get_system_health()

    # Determine overall status
    overall_status = "healthy"
    if any(component["status"] != "up" for component in health.values()):
        overall_status = "unhealthy"

    return {
        "status": overall_status,
        "components": health,
        "timestamp": time.time()
    }

@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    # This would integrate with prometheus_client
    return Response(
        content=generate_prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )
```

#### Prometheus Configuration

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  # - "first_rules.yml"
  # - "second_rules.yml"

scrape_configs:
  - job_name: 'megabot'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 5s

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis:9121']
```

### Logging Configuration

#### Structured Logging (`logging.py`)

```python
import logging
import json
from pythonjsonlogger import jsonlogger

def setup_logging(level: str = "INFO"):
    """Configure structured JSON logging."""

    # Create logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper()))

    # Create JSON formatter
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler for errors
    file_handler = logging.FileHandler("logs/error.log")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# Usage in application
logger = setup_logging(os.getenv("LOG_LEVEL", "INFO"))
```

### Alerting

#### AlertManager Configuration

```yaml
global:
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alerts@megabot.com'
  smtp_auth_username: 'alerts@megabot.com'
  smtp_auth_password: 'password'

route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'email'

receivers:
  - name: 'email'
    email_configs:
      - to: 'admin@megabot.com'
        send_resolved: true

  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR_SLACK_WEBHOOK_URL'
        channel: '#alerts'
        send_resolved: true
```

## Rollback Procedures

### Automated Rollback

```bash
#!/bin/bash
# rollback.sh

set -e

echo "Starting rollback procedure..."

# Get previous deployment
PREVIOUS_VERSION=$(aws ecs describe-services \
  --cluster megabot-production \
  --services megabot-service \
  --query 'services[0].taskDefinition' \
  --output text | awk -F'/' '{print $2}' | awk -F':' '{print $2}')

# Update to previous version
aws ecs update-service \
  --cluster megabot-production \
  --service megabot-service \
  --task-definition megabot:$PREVIOUS_VERSION \
  --force-new-deployment

# Wait for rollback to complete
aws ecs wait services-stable \
  --cluster megabot-production \
  --services megabot-service

# Verify rollback
curl -f ${{ secrets.PRODUCTION_URL }}/health

echo "Rollback completed successfully"
```

### Manual Rollback Steps

1. **Identify the issue**: Check logs, metrics, and error reports
2. **Stop the problematic deployment**:
   ```bash
   aws ecs update-service --cluster megabot-production --service megabot-service --desired-count 0
   ```
3. **Deploy the previous version**:
   ```bash
   aws ecs update-service --cluster megabot-production --service megabot-service --task-definition megabot:previous-version
   ```
4. **Verify the rollback**:
   ```bash
   aws ecs wait services-stable --cluster megabot-production --services megabot-service
   curl -f ${{ secrets.PRODUCTION_URL }}/health
   ```
5. **Update the load balancer** if necessary
6. **Notify stakeholders** about the rollback

## Security in CI/CD

### Secret Management

```yaml
# GitHub Secrets (Settings > Secrets and variables > Actions)
# AWS_ACCESS_KEY_ID
# AWS_SECRET_ACCESS_KEY
# DOCKER_USERNAME
# DOCKER_PASSWORD
# SNYK_TOKEN
# SLACK_WEBHOOK_URL
# ANTHROPIC_API_KEY (for staging deployments)
```

### Dependency Scanning

```yaml
# .github/workflows/dependency-scan.yml
name: Dependency Scan
on:
  schedule:
    - cron: '0 0 * * *'  # Daily
  push:
    branches: [ main ]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run safety check
        uses: LFortran/fortlsafety-action@v1
        with:
          file: requirements.txt

      - name: Run OSV scanner
        uses: google/osv-scanner-action@v1
        with:
          scan-args: |
            --recursive .
            --skip-git
```

### Image Security

```yaml
# Dockerfile security best practices
FROM python:3.11-slim

# Install security updates
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash app

# Install dependencies as non-root
USER app
```

This CI/CD guide provides a comprehensive framework for automated testing, building, deployment, and monitoring of MegaBot, ensuring reliable and secure delivery of updates to production environments.</content>
<parameter name="filePath">docs/development/ci-cd.md