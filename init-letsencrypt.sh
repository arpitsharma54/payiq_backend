#!/bin/bash

# SSL Certificate Initialization Script for Let's Encrypt
# This script initializes SSL certificates for the first time

set -e

# Configuration
DOMAIN=${1:-""}
EMAIL=${2:-""}
STAGING=${3:-0}  # Set to 1 for testing (avoids rate limits)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_usage() {
    echo "Usage: $0 <domain> <email> [staging]"
    echo ""
    echo "Arguments:"
    echo "  domain   - Your domain name (e.g., example.com)"
    echo "  email    - Email for Let's Encrypt notifications"
    echo "  staging  - Set to 1 for testing (optional, default: 0)"
    echo ""
    echo "Example:"
    echo "  $0 example.com admin@example.com"
    echo "  $0 example.com admin@example.com 1  # Staging mode"
}

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo -e "${RED}Error: Domain and email are required${NC}"
    print_usage
    exit 1
fi

echo -e "${GREEN}Starting SSL certificate initialization...${NC}"
echo "Domain: $DOMAIN"
echo "Email: $EMAIL"
echo "Staging: $STAGING"
echo ""

# Create required directories
echo -e "${YELLOW}Creating certificate directories...${NC}"
mkdir -p ./certbot/conf
mkdir -p ./certbot/www

# Check if certificate already exists
if [ -d "./certbot/conf/live/$DOMAIN" ]; then
    echo -e "${YELLOW}Certificate already exists for $DOMAIN${NC}"
    read -p "Do you want to replace it? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborting..."
        exit 0
    fi
fi

# Create dummy certificate for nginx to start
echo -e "${YELLOW}Creating dummy certificate for nginx startup...${NC}"
DUMMY_CERT_PATH="./certbot/conf/live/$DOMAIN"
mkdir -p "$DUMMY_CERT_PATH"

docker compose run --rm --entrypoint "\
    openssl req -x509 -nodes -newkey rsa:4096 -days 1 \
    -keyout '/etc/letsencrypt/live/$DOMAIN/privkey.pem' \
    -out '/etc/letsencrypt/live/$DOMAIN/fullchain.pem' \
    -subj '/CN=localhost'" certbot

# Create chain.pem (copy of fullchain for OCSP)
docker compose run --rm --entrypoint "\
    cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem /etc/letsencrypt/live/$DOMAIN/chain.pem" certbot

echo -e "${GREEN}Dummy certificate created${NC}"

# Start nginx with dummy certificate
echo -e "${YELLOW}Starting nginx...${NC}"
docker compose up -d nginx
sleep 5

# Delete dummy certificate
echo -e "${YELLOW}Removing dummy certificate...${NC}"
docker compose run --rm --entrypoint "\
    rm -rf /etc/letsencrypt/live/$DOMAIN && \
    rm -rf /etc/letsencrypt/archive/$DOMAIN && \
    rm -rf /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

# Request real certificate
echo -e "${YELLOW}Requesting Let's Encrypt certificate...${NC}"

STAGING_ARG=""
if [ "$STAGING" = "1" ]; then
    STAGING_ARG="--staging"
    echo -e "${YELLOW}Using staging environment (certificates won't be trusted)${NC}"
fi

docker compose run --rm --entrypoint "\
    certbot certonly --webroot -w /var/www/certbot \
    $STAGING_ARG \
    --email $EMAIL \
    --domain $DOMAIN \
    --rsa-key-size 4096 \
    --agree-tos \
    --no-eff-email \
    --force-renewal" certbot

# Reload nginx with real certificate
echo -e "${YELLOW}Reloading nginx with new certificate...${NC}"
docker compose exec nginx nginx -s reload

echo ""
echo -e "${GREEN}SSL certificate successfully obtained!${NC}"
echo ""
echo "Next steps:"
echo "1. Update your .env file with: DOMAIN=$DOMAIN"
echo "2. Restart all services: docker compose up -d"
echo "3. The certbot container will automatically renew certificates"
echo ""
echo -e "${YELLOW}Note: Certificates will auto-renew every 12 hours if needed${NC}"
