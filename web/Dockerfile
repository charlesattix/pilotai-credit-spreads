FROM node:18-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install --legacy-peer-deps

COPY . .
RUN rm -f package-lock.json && npm run build

ENV PORT=3000
EXPOSE 3000

CMD ["npm", "run", "start"]
