FROM http-prism-soil:latest

RUN apt -y update \
 && apt -y upgrade

ARG APP_REPO
RUN git clone --recurse-submodules "$APP_REPO"

ARG APP_VERSION
ARG APP_BRANCH
RUN cd /app/uwsgi \
 && git pull origin "$APP_BRANCH" \
 && git checkout "$APP_VERSION" \
 && pip install --no-cache-dir .

COPY ./app.py /app

CMD "uwsgi" "--http" "0.0.0.0:80" "--wsgi-file" "/app/app.py" "--callable" "app"
