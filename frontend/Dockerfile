# ==========================================
# Stage 1: Build Frontend SPA
# ==========================================
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies with caching
COPY package.json package-lock.json ./
RUN npm ci || npm install

# Copy source and build assets
COPY . .
RUN npm run build

# ==========================================
# Stage 2: Production Nginx Static Server
# ==========================================
FROM nginx:alpine

# Clean default static files
RUN rm -rf /usr/share/nginx/html/*

# Copy compiled assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy SPA Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
