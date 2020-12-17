# FAQ

## Key generation

- Increase entropy and speed up key generation:

  ```sh
  sudo apt-get install rng-tools
  sudo rngd -r /dev/urandom
  ```

## Raspberry Pi

- Failed to launch `numpy` with error `Original error was: libf77blas.so.3: cannot open shared object file: No such file or directory`:

  ```sh
  apt install libatlas-base-dev
  ```

- `ImportError: libopenjp2.so.7: cannot open shared object file: No such file or directory`

  ```sh
  apt install libopenjp2-7
  ```

- `ImportError: libtiff.so.5: cannot open shared object file: No such file or directory`

  ```sh
  apt install libtiff5
  ```

- Install WireGuard:

  ```sh
  # Trust debian's apt repository
  apt-key adv --keyserver hkp://p80.pool.sks-keyservers.net:80 --recv-keys 04EE7237B7D453EC 648ACFD622F3D138
  # Add debian's apt repository
  echo 'deb http://deb.debian.org/debian/ unstable main' >> /etc/apt/sources.list.d/unstable.list
  printf 'Package: *\nPin: release a=unstable\nPin-Priority: 90\n' >> /etc/apt/preferences.d/limit-unstable
  apt update
  apt install wireguard raspberrypi-kernel-headers
  ```

- Enable passwordless `sudo` (for testing only):

  - Create a group for passwordless sudo'ers:

    ```sh
    groupadd sudoless
    ```

  - Edit `/etc/sudoers`, and a line after `#includedir /etc/sudoers.d`:

    ```sh
    # Allow password-less sudo for members of group sudoless
    %sudoless      ALL=(ALL) NOPASSWD: ALL
    ```

  - Add user to group:

    ```sh
    usermod -a -G sudoless pi
    ```
