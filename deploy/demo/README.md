# Public demo

Runs the [demo stack](../../docker-compose.demo.yml) somewhere the internet can
reach it — what App Store / TestFlight reviewers sign in to, since they cannot
join your tailnet. Synthetic data only.

It is the base demo stack plus three changes: a Cloudflare Tunnel in place of
an open port, non-default passwords, and a nightly wipe-and-reseed.

## Set up

1. **Create the tunnel.** Cloudflare dashboard → Zero Trust → Networks →
   Tunnels → Create a tunnel (Cloudflared). Copy the token from the install
   command it shows, then add a public hostname with service `http://app:8001`.
   Cloudflare creates the DNS record and certificate.

2. **Check out the repo** on the host, separately from any real deployment:

   ```sh
   git clone https://github.com/aderaaij/loopback-training-server.git ~/loopback-demo
   cd ~/loopback-demo
   cp deploy/demo/.env.example deploy/demo/.env   # then fill it in
   ```

3. **Bring it up** (also the command to reset it by hand):

   ```sh
   ./deploy/demo/reset.sh
   ```

4. **Reset it nightly:**

   ```sh
   mkdir -p ~/.config/systemd/user
   cp deploy/demo/loopback-demo-reset.{service,timer} ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now loopback-demo-reset.timer
   ```

   The service file assumes the checkout is at `~/loopback-demo`. User timers
   only run while logged out if lingering is on: `loginctl enable-linger`.

## Take it down

```sh
docker compose --env-file deploy/demo/.env \
  -f docker-compose.demo.yml -f deploy/demo/docker-compose.public.yml down --volumes
systemctl --user disable --now loopback-demo-reset.timer
```

## Things to know

- The demo account is a normal, writable account. Anyone holding its password
  can change it or upload data; the nightly reset is what undoes that. Share
  the password in review notes only.
- A reviewer's phone syncs its own Apple Health data to the demo on sign-in.
  The reset removes it.
- Every request arrives from the tunnel container, so the login rate limit
  (5 per minute) is shared by all visitors rather than per client.
- The stack tracks the `latest` image; each reset pulls it.
