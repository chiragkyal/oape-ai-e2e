FROM golang:1.23 AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /go-server .

FROM registry.access.redhat.com/ubi9-minimal:latest
COPY --from=builder /go-server /usr/local/bin/go-server
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/go-server"]
