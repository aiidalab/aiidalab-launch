# Forward AiiDAlab from a remote machine via SSH

In some cases you might want to run AiiDAlab on a remote server with SSH access and open it in the browser of your local computer.
This can be easily achieved by creating an SSH tunnel and forwarding the AiiDAlab port from the remote to the local machine.

1. On your local computer, use ssh to log into the remote machine, example:
    ```console
    $ ssh user@my-server.org
    ```
    _Please make sure to replace the server username and address with those applicable to your remote machine._

2. Then, logged into the remote machine, follow the [instructions to launch AiiDAlab](README.md#getting-started), e.g.,
    ```console
    $ aiidalab-launch start --no-browser --show-ssh-port-forwarding-help
    ````
    - The `--no-browser` option tells the launcher that we do not want to directly open AiiDAlab after starting the instance.
    - The `--show-ssh-port-forwarding-help` option instructs the launcher to provide some help on the command neded for SSH port forwarding.

    _Usually the launcher will be able to detect that you are starting AiiDAlab on a headless remote machine in which case aforementioned options are automatically selected._

3. Wait for AiiDAlab to start and note down the provided ssh command and URL.

4. Either open a separate terminal on your local computer, or log out of your remote machine.
   Then run the SSH port-forwarding command, which will look something like this:
   ```console
   $ ssh user@my-server.org -NfL 8888:localhost:8888
   ```

5. Finally, open AiiDAlab in the browser of your local machine via the URL provided earlier, something like: http://localhost:8888/?token=74647d5fe0...
