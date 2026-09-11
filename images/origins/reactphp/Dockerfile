FROM http-prism-soil:latest

RUN apt -y update \
 && apt -y upgrade \
 && apt -y install --no-install-recommends php-cli php-mbstring php-xml php-curl composer

ARG APP_REPO
RUN git clone --recurse-submodules "$APP_REPO"

ARG APP_VERSION
ARG APP_BRANCH
RUN cd /app/http \
 && git pull origin "$APP_BRANCH" \
 && git checkout "$APP_VERSION" \
 && composer install --no-dev --no-interaction --no-progress

COPY ./server.php /app

CMD ["php", "/app/server.php"]
