# One time
brew install gh

# Every time
gh auth login
docker run --privileged --rm tonistiigi/binfmt --install all
docker buildx create --name multiarch --use --bootstrap
gh auth refresh -h github.com -s write:packages
docker logout ghcr.io
gh auth token | docker login ghcr.io -u dannysia --password-stdin
docker buildx build --platform linux/amd64,linux/arm64   -t ghcr.io/dannysia/tubearchivist:mainline   --push .
