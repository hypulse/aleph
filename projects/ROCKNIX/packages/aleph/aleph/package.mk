# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026-present aleph (https://github.com/hypulse/aleph)

PKG_NAME="aleph"
PKG_VERSION=""
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/hypulse/aleph"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain alephd aleph-shell mpd pretendard koreader portmaster"
PKG_NEED_UNPACK="${ROOT}/aleph/system"
PKG_LONGDESC="aleph: an iPod-inspired, music-first shell with its system services"
PKG_TOOLCHAIN="manual"

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/share/aleph
  cp ${ROOT}/aleph/system/sway.conf ${INSTALL}/usr/share/aleph/
  cp -r ${ROOT}/aleph/system/mpv ${INSTALL}/usr/share/aleph/
  cp -r ${ROOT}/aleph/system/koreader ${INSTALL}/usr/share/aleph/

  # alephd reads the buttons, the lid and the power key itself, and aleph reports
  # nothing to ROCKNIX's install statistics.
  mkdir -p ${INSTALL}/etc/systemd/system
  for UNIT in input.service rocknix-report-stats.service rocknix-report-stats.timer; do
    ln -sf /dev/null ${INSTALL}/etc/systemd/system/${UNIT}
  done
}

post_install() {
  enable_service alephd.service
}
