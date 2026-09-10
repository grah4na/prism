FROM http-prism-soil:latest

RUN apt -y update \
 && apt -y upgrade \
 && apt -y install --no-install-recommends cmake

ARG APP_REPO
RUN git clone --recurse-submodules "$APP_REPO"

ARG APP_VERSION
ARG APP_BRANCH
RUN cd /app/libevent \
 && git pull origin "$APP_BRANCH" \
 && git checkout "$APP_VERSION" \
 && cmake . \
 && make "-j$(nproc)"

COPY ./http-prism.c /app/libevent/sample/http-prism.c
RUN cd /app/libevent \
 && $CC $CFLAGS -Wall -Wextra -Iinclude sample/http-prism.c lib/libevent.a -o http-prism

CMD "/app/libevent/http-prism"
