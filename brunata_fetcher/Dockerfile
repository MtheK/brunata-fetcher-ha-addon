ARG BUILD_FROM
FROM ${BUILD_FROM}

# Use Debian base for Playwright stability (glibc-based runtime).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /tmp/requirements.txt

# Install Chromium and required system dependencies for Playwright.
RUN playwright install chromium --with-deps

# Copy add-on scripts
COPY *.py /app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /app
CMD ["/run.sh"]
