# Comparative Sequencing Analysis Platform - Web API

[![GitHub issues](https://img.shields.io/github/issues/MBaysanLab/cosap-webapi)](https://github.com/MBaysanLab/cosap-webapi/issues)
[![GitHub license](https://img.shields.io/github/license/MBaysanLab/cosap-webapi)](https://github.com/MBaysanLab/cosap-webapi/blob/main/LICENSE)

RESTful web API implementation to interact with [Comparative Sequencing Analysis Platform](https://github.com/MBaysanLab/cosap).

__Disclamier__: This software is in constant development and NOT READY TO BE USED IN PRODUCTION.

# Running the Development Server
As a first step, you need to have [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) set up. While running the server without Docker might be technically possible, it may require modifications to the source code and is not recommended.

### Clone the git repository:

    git clone https://github.com/MBaysanLab/cosap-webapi.git
    cd cosap-webapi

### Set necessary variables in your environment:

| Variable | Description |
| --- | --- |
| `COSAP_DJANGO_SECRET` | A secret key used for signing purposes. Should be set to a unique, unpredictable value and kept secret. Mandatory.
| `COSAP_DJANGO_HOST` | Host/domain name that the server can serve. Optional; if empty or not set, only connections from localhost are allowed. |
| `COSAP_DJANGO_DEBUG` | Set to "True" if you want to allow Django debug output. Optional, debug is disabled by default. |

If you don't want to set the environment variables in the host environment, you can just replace the environment variables with their values in the [docker-compose.yaml](docker-compose.yaml) file.

### Run the containers:

    docker compose up -d

This command will build the container image and run the containers in detached mode. If you are building the image for the first time, it might take some time as it requires around 1GB of packages to be downloaded.

You might also need to update the database structure after the containers are started:

    docker compose exec web bash -l -c "python manage.py makemigrations && python manage.py migrate"

#### The development server should now be accessible at [http://localhost:8000](http://localhost:8000).

You can view the logs with:

    docker compose logs -f -t

You can stop and remove the containers with:

    docker compose down
