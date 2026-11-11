# Malware scanner VM

RecallTrace keeps every uploaded evidence file in quarantine until a malware scanner
reports it clean. This folder runs that scanner on one small Linux VM:

- `scanner_service.py`: a standard-library HTTP service. `POST /scan` with
  `Authorization: Bearer <SCANNER_TOKEN>` returns `{"status": "clean"}` or
  `{"status": "infected"}`; anything else (wrong token, ClamAV down) is refused or
  reported as unavailable, so the file stays quarantined. `GET /health` reports
  whether ClamAV is answering.
- `setup.sh`: installs ClamAV with daily signature updates, the service (as a
  hardened systemd unit) and Caddy for automatic HTTPS, then prints the endpoint
  and a newly generated token.

## Sizing

ClamAV holds its signatures in memory (about 1.2 GB). Use a VM with at least 2 GB of
RAM, for example Azure **B1ms** (1 vCPU, 2 GB). The free B1s (1 GB) is too small. The
script adds 2 GB of swap and disables concurrent signature reloads so daily updates do
not double memory use.

## Set up on Azure (Azure for Students)

1. Create a virtual machine: Ubuntu Server 24.04 LTS, size B1ms, region Central India
   (closest to the Mumbai app), SSH key authentication, inbound ports 22, 80 and 443.
2. On the VM's public IP address, set a DNS name label, for example `recalltrace-scan`,
   giving `recalltrace-scan.centralindia.cloudapp.azure.com`.
3. Connect with SSH and run:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/Muhammad-Faizan-1606/Recall-Trace/main/operations/scanner/setup.sh | sudo bash -s -- recalltrace-scan.centralindia.cloudapp.azure.com
   ```

4. Add the printed values as GitHub repository secrets `SCANNER_ENDPOINT` and
   `SCANNER_TOKEN`, then run the "Deploy backend to Vercel" workflow. The deploy turns
   real scanning on automatically when both secrets exist.

## Check it

```sh
curl https://recalltrace-scan.centralindia.cloudapp.azure.com/health
```

`{"status": "ready"}` means ClamAV is loaded. Logs: `journalctl -u recalltrace-scanner`
and `journalctl -u clamav-daemon`. Rotate the token by deleting
`/etc/recalltrace-scanner.env`, rerunning `setup.sh`, and updating the GitHub secret.
