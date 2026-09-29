# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026-present aleph (https://github.com/hypulse/aleph)

PKG_NAME="aleph-shell"
PKG_VERSION=""
PKG_LICENSE="GPL-2.0-or-later"
PKG_SITE="https://github.com/hypulse/aleph"
PKG_URL=""
PKG_DEPENDS_TARGET="toolchain SDL2 SDL2_ttf SDL2_image"
PKG_NEED_UNPACK="${ROOT}/aleph/shell"
PKG_LONGDESC="aleph shell: the iPod-inspired user interface"
PKG_TOOLCHAIN="make"

unpack() {
  mkdir -p ${PKG_BUILD}
  cp -a ${ROOT}/aleph/shell/. ${PKG_BUILD}/
  rm -f ${PKG_BUILD}/aleph-shell
}

make_target() {
  make CC="${CC}"
}

makeinstall_target() {
  mkdir -p ${INSTALL}/usr/bin ${INSTALL}/usr/share/aleph
  cp ${PKG_BUILD}/aleph-shell ${INSTALL}/usr/bin/
  cp -r ${PKG_BUILD}/assets/. ${INSTALL}/usr/share/aleph/
}
