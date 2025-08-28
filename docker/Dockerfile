FROM debian:bullseye

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

SHELL [ "/bin/bash", "--login", "-c" ]

RUN apt update && apt install -y wget git

# Install Miniconda
WORKDIR /tmp
# Determine the system type and OS
RUN uname -m > /tmp/system_type

# Install Miniconda based on the system type and OS
RUN if [ $(cat /tmp/system_type) = "x86_64" ]; then \
        wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh; \
    elif [ $(cat /tmp/system_type) = "aarch64" ]; then \
        wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O miniconda.sh; \
    else \
        echo "Unsupported system"; \
        exit 1; \
    fi

RUN bash miniconda.sh -b -p /app/miniconda && rm miniconda.sh
ENV PATH="/app/miniconda/bin:${PATH}"
RUN echo export PATH="/app/miniconda/bin:${PATH}" >> ~/.bashrc && echo ". ~/.bashrc" >> ~/.bash_profile
RUN conda init bash

# Install web API requirements
RUN pip install uv
COPY requirements.txt /tmp/requirements.txt
RUN uv pip install -r /tmp/requirements.txt

# Copy application code
WORKDIR /webapi
COPY . /webapi/

# Create a non-root user for security
RUN useradd -m -u 1000 cosap && chown -R cosap:cosap /webapi

# Ensure PATH is set for the cosap user
RUN echo 'export PATH="/app/miniconda/bin:${PATH}"' >> /home/cosap/.bashrc
RUN echo 'source ~/.bashrc' >> /home/cosap/.bash_profile

USER cosap

# Ensure conda environment is activated
RUN echo 'source ~/.bashrc' >> ~/.profile