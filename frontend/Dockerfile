FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "5173"]
