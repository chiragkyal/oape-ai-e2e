FROM registry.access.redhat.com/ubi9/go-toolset AS builder
WORKDIR /go/src/app

COPY ./go-server/go.mod ./go-server/go.sum . 

RUN go mod download
COPY ./go-server .
RUN go build -o /tmp/app .

FROM registry.access.redhat.com/ubi9-minimal:latest
COPY --from=builder /tmp/app /usr/local/bin/app-server
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/app-server"]
