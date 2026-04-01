FROM alpine:3.22

RUN apk add --no-cache bash git openssh-server \
    && adduser -D -h /home/git -s /usr/bin/git-shell git \
    && mkdir -p /var/run/sshd /config /home/git/.ssh /home/git/repos \
    && chown -R git:git /home/git \
    && chmod 700 /home/git/.ssh

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 2222
ENTRYPOINT ["/entrypoint.sh"]
