FROM http-prism-soil:latest

RUN apt -y update \
 && apt -y upgrade \
 && apt -y install --no-install-recommends ruby-dev \
 && gem install rack \
 && ln -sf /usr/bin/gcc "/usr/bin/$(uname -m)-linux-gnu-gcc" \
 && ln -sf /usr/bin/g++ "/usr/bin/$(uname -m)-linux-gnu-g++"

ARG APP_REPO
RUN git clone --recurse-submodules "$APP_REPO"

ARG APP_VERSION
ARG APP_BRANCH
RUN cd /app/thin \
 && git pull origin "$APP_BRANCH" \
 && git checkout "$APP_VERSION" \
 && gem build \
 && gem install ./thin*.gem

COPY ./config.ru .

CMD "thin" "-p" "80" "-R" "config.ru" "start"
