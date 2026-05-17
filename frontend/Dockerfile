FROM node:20-alpine

WORKDIR /app

# Install dependencies first for better caching
COPY package*.json ./
RUN npm install

# Copy the rest of the application
COPY . .

# Expose Vite's default port
EXPOSE 5173

# Start Vite dev server and expose it to all network interfaces
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
