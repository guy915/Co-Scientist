# syntax=docker/dockerfile:1
# Use official Bun image
FROM oven/bun:1.3.14

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json bun.lock ./

# Install dependencies
RUN bun install --frozen-lockfile

# Copy the rest of the application
COPY . .

# Expose Vite dev server port
EXPOSE 5173

# Run Vite dev server
CMD ["bun", "run", "dev", "--host", "0.0.0.0"]
