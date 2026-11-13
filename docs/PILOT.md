# Styri Pilot

Styri Core covers up to three robots. Styri Pilot covers up to 20 on one site. The
panel, the fleet view, control and VDA 5050 are the same in both.

Pilot runs from the **Styri Pro** image, `ghcr.io/styri-dev/styri-pro`
(public, amd64 and arm64). **Without a license file the Pro image is Styri
Core:** up to three robots. A Styri Pilot license, which you receive by email
after you buy, raises that.

## Install

1. **List your robots** in `styri.yaml` ([MAPPING.md](MAPPING.md)), told
   apart by namespace and/or ROS domain:

   ```yaml
   robots:
     - robot: {name: amr-1, namespace: /amr1}
     - robot: {name: amr-2, namespace: /amr2}
     - robot: {name: amr-3, domain_id: 43}
   ```

2. **Put the license file next to it**, as `license.json`. Keep it as it
   arrived: any change, even a space, makes it invalid.

3. **Run Styri Pro** with both files mounted:

   ```bash
   docker run -d --name styri --restart unless-stopped --network host \
     -v "$PWD/styri.yaml:/etc/styri/styri.yaml:ro" \
     -v "$PWD/license.json:/etc/styri/license.json:ro" \
     -v styri-data:/var/lib/styri \
     ghcr.io/styri-dev/styri-pro:v2.0.1
   ```

   `/etc/styri/license.json` is where Styri looks. To keep the license
   elsewhere, mount it anywhere and set `-e STYRI_LICENSE_FILE=/that/path`.
   The `styri-data` volume keeps the activity log across restarts.

4. **Check it:**
   - Open the panel on port 8080: the **Fleet** tab lists your robots.
   - `styri check` tests every robot's mapping against the live network:
     `docker exec styri /ros_entrypoint.sh styri check`.
   - `styri-license verify` reads the license back:
     `docker exec styri styri-license verify /etc/styri/license.json`.

### Without registry access

Download the release from
[styri-dev/styri-pro-releases](https://github.com/styri-dev/styri-pro-releases/releases):
an image tarball per architecture, with `SHA256SUMS.txt`. Copy the tarball for
the site's machine (`uname -m`: `x86_64` is amd64, `aarch64` is arm64), then:

```bash
sha256sum -c --ignore-missing SHA256SUMS.txt
docker load < styri-pro-v2.0.1-linux-amd64.tar.gz
```

and run it as above. Air-gapped Kubernetes: the same releases have signed Zarf
packages; that repository's README shows the install.

## The license

- **Offline.** Styri checks the file's signature on the machine itself and
  never contacts anyone. It needs no internet, ever.
- **Checked at start.** Restart Styri after installing or renewing a license.
- **Over the limit:** if `styri.yaml` lists more robots than the license
  covers, the panel shows the first ones and says so.
- **Expiry:** an expired license keeps the fleet working for 14 more days,
  with a notice on every screen, so nothing stops in the middle of a shift.
  After that the panel shows three robots, like Styri Core, until the license
  is renewed.
- **No license, or one that isn't valid:** three robots, like Styri Core, and a
  notice saying why when your file lists more than three.

Questions, renewals, more robots: [hello@styri.dev](mailto:hello@styri.dev).
