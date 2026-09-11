FROM http-prism-soil:latest

RUN apt -y update \
 && apt -y upgrade \
 && apt -y install --no-install-recommends bzip2

ARG APP_REPO
RUN git clone --recurse-submodules "$APP_REPO"

ARG APP_VERSION
ARG APP_BRANCH
COPY ./echo-catchall.patch /app/echo-catchall.patch
# NOTE: plain gcc build; busybox's build system does not honor the soil
# clang/sanitizer flags, and needs the bzip2 host tool above.
# Only the httpd applet (+CGI) is enabled: trixie's kernel headers no
# longer ship the CBQ structs networking/tc.c needs, and nothing else
# in the binary is used at runtime (echo.cgi runs under /bin/sh).
RUN cd /app/busybox \
 && git pull origin "$APP_BRANCH" \
 && git checkout "$APP_VERSION" \
 && git apply /app/echo-catchall.patch \
 && unset CC CXX CFLAGS CXXFLAGS LDFLAGS \
 && make allnoconfig \
 && sed -i -e 's/# CONFIG_HTTPD is not set/CONFIG_HTTPD=y/' -e 's/# CONFIG_FEATURE_HTTPD_CGI is not set/CONFIG_FEATURE_HTTPD_CGI=y/' .config \
 && yes "" | make oldconfig \
 && make "-j$(nproc)"

RUN mkdir -p /www/cgi-bin
COPY ./echo.cgi /www/cgi-bin/index.cgi
RUN cp /www/cgi-bin/index.cgi /www/cgi-bin/echo \
 && chmod +x /www/cgi-bin/index.cgi /www/cgi-bin/echo

CMD ["/app/busybox/busybox", "httpd", "-f", "-p", "80", "-h", "/www"]
