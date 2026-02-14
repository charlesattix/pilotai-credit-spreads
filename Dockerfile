# Stage 1: Node.js dependencies
FROM node:20-slim AS node-deps
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --ignore-scripts

# Stage 2: Build Next.js
FROM node:20-slim AS web-build
WORKDIR /app/web
COPY --from=node-deps /app/web/node_modules ./node_modules
COPY web/ .
RUN npm run build

# Stage 3: Runtime
FROM python:3.11-slim

# Install Node.js runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Python backend
COPY *.py ./
COPY strategy/ ./strategy/
COPY ml/ ./ml/
COPY backtest/ ./backtest/
COPY tracker/ ./tracker/
COPY alerts/ ./alerts/
COPY shared/ ./shared/
COPY config.yaml .

# Copy built Next.js app
COPY --from=web-build /app/web/.next/standalone ./web/
COPY --from=web-build /app/web/.next/static ./web/.next/static
COPY --from=web-build /app/web/public ./web/public

# Create non-root user
RUN useradd -r -s /bin/false appuser && \
    mkdir -p /app/data /app/output /app/logs && \
    chown -R appuser:appuser /app
USER appuser

# Copy entrypoint
COPY docker-entrypoint.sh .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/api/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["web"]
