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
ENV NODE_ENV=production
RUN npm run build

# Stage 3: Runtime
FROM python:3.11-slim

# Install Node.js 20 from official binary (no piped shell scripts)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates tini xz-utils && \
    DPKG_ARCH=$(dpkg --print-architecture) && \
    NODE_ARCH=$(case "${DPKG_ARCH}" in amd64) echo "x64" ;; arm64) echo "arm64" ;; *) echo "${DPKG_ARCH}" ;; esac) && \
    curl -fsSL "https://nodejs.org/dist/v20.20.0/node-v20.20.0-linux-${NODE_ARCH}.tar.xz" \
      | tar -xJ --strip-components=1 -C /usr/local && \
    apt-get purge -y xz-utils && apt-get autoremove -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Set production environment
ENV NODE_ENV=production
ENV PORT=8080
ENV HOSTNAME=0.0.0.0

# Install Python dependencies
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$BUILD_ENV" = "dev" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

# Copy Python backend
COPY *.py ./
COPY strategy/ ./strategy/
COPY ml/ ./ml/
COPY backtest/ ./backtest/
COPY tracker/ ./tracker/
COPY alerts/ ./alerts/
COPY shared/ ./shared/
COPY config.yaml.example ./config.yaml

# Copy built Next.js app
COPY --from=web-build /app/web/.next/standalone ./web/
COPY --from=web-build /app/web/.next/static ./web/.next/static
COPY --from=web-build /app/web/public ./web/public

# Copy entrypoint BEFORE switching to non-root user
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# Initialize SQLite database and create non-root user
RUN python -c "from shared.database import init_db; init_db()" && \
    useradd -r -s /bin/false appuser && \
    mkdir -p /app/data /app/output /app/logs && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "./docker-entrypoint.sh"]
CMD ["web"]
