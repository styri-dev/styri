# Simulated VDA 5050 vehicle for tests and the mixed-fleet demo. Not part of the
# product image.
FROM node:24-alpine
WORKDIR /opt/vda-sim
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY sim.js factsheet.json ./
USER node
CMD ["node", "sim.js"]
