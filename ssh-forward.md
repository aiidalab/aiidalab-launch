### Forward AiiDAlab from a remote server via SSH

In some cases you might want to run AiiDAlab on a remote server with SSH access and open it in the browser of your local computer.
This can be easily achieved by creating a SSH tunnel between the remote and the local machine.

1. Follow the [instructions to launch AiiDAlab](README.md#getting-started) on the remote machine, e.g.,
    ```console
    aiidalab-launch start --no-browser
    ````
    We use the `--no-browser` option since we do not intend to open AiiDAlab in the browser on the remote machine.
2. Wait for AiiDAlab to start and inspect the URL which will look something like this: http://localhost:8888/?token=74647d5fe0...
3. Determine the port on which the AiiDAlab instance is accessible, in this case it is: **8888**.
4. Forward port 8888 via SSH to your local machine with a command similar to this:
   ```console
   ssh user@my-server.org -L 8888:localhost:8888
   ```
   _Please make sure to replace the server username and address with the one applicable to you remote machine._
5. You can now open AiiDAlab in the browser of your local machine directly via the URL from above.
