# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026-present aleph (https://github.com/hypulse/aleph)

PKG_NAME="alephd"
PKG_VERSION=""
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/hypulse/aleph"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain Python3 dbussy pyudev"
PKG_NEED_UNPACK="${ROOT}/aleph/daemon"
PKG_LONGDESC="aleph system daemon: input, music, radio, Bluetooth, Wi-Fi, power and apps"
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/lib/aleph ${INSTALL}/usr/bin
  cp -r ${ROOT}/aleph/daemon/aleph ${INSTALL}/usr/lib/aleph/
  find ${INSTALL}/usr/lib/aleph -name __pycache__ -prune -exec rm -rf {} +
  cat >${INSTALL}/usr/bin/alephd <<'EOF'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/lib/aleph")
from aleph.main import main
main()
EOF
  chmod 0755 ${INSTALL}/usr/bin/alephd
}
