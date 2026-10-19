# Changelog

## [0.4.0](https://github.com/trozzelle/OfflineDAoC-macOS/compare/v0.3.0...v0.4.0) (2026-10-19)


### Features

* Offline DAoC 0.37, with the server built from our own server repo ([02952dc](https://github.com/trozzelle/OfflineDAoC-macOS/commit/02952dccf2794c760dba00769b58253e05f42846))
* Offline DAoC 0.37, with the server built from our own server repo ([f0ec4a1](https://github.com/trozzelle/OfflineDAoC-macOS/commit/f0ec4a1858a3b36ac83e9b6bc9c6c0a7ce8cf92b))
* **server:** 0.35 and 0.36 ship the classic quests' data; new client update fixes ([e39f15b](https://github.com/trozzelle/OfflineDAoC-macOS/commit/e39f15b6bb42aa0d15f0008ef7792286210087a4))
* **server:** 0.37 follows its own macos-0.37 branch ([e4f82c0](https://github.com/trozzelle/OfflineDAoC-macOS/commit/e4f82c009b6721ab5a36eff3bd9003dec4dfaabf))


### Bug Fixes

* **client:** no fetch line when the new client has nothing left to fetch ([90b3db1](https://github.com/trozzelle/OfflineDAoC-macOS/commit/90b3db1e2a84cc3021937bda71a7d0f22915bfdf))
* **e2e:** its own server install records the selected edition ([7418850](https://github.com/trozzelle/OfflineDAoC-macOS/commit/741885025a8f62f8c54f174fc6867c5c6be61be3))

## [0.3.0](https://github.com/trozzelle/OfflineDAoC-macOS/compare/v0.2.0...v0.3.0) (2026-10-18)


### Features

* **client:** install the new client natively under Godot ([326922d](https://github.com/trozzelle/OfflineDAoC-macOS/commit/326922dffd360e27f5eab4b56e2f32272f28f166))
* **client:** original client editions; classic game.dll is a Proven build ([a320085](https://github.com/trozzelle/OfflineDAoC-macOS/commit/a32008568a8b2fdc44018d24e35e5113fc67b6f5))
* **client:** start, stop and kill the new client ([04f5e2b](https://github.com/trozzelle/OfflineDAoC-macOS/commit/04f5e2b037b3dd76ca43aa9c77bb9aff130c9c33))
* **game:** daoc game switch ([3648916](https://github.com/trozzelle/OfflineDAoC-macOS/commit/36489161b3c108b1e94979a3142608bf73804804))
* **game:** schema 2 manifest with per-version pins ([d133ebf](https://github.com/trozzelle/OfflineDAoC-macOS/commit/d133ebf8193ee5becfa3d82eb4cd1e3292d39ff4))
* **game:** the Selection, inferred for existing checkouts ([c4fcc20](https://github.com/trozzelle/OfflineDAoC-macOS/commit/c4fcc20fc5dba29f6b1723e71bb6d8ec07d4ae11))
* **overview:** show the game, both clients and the save edition ([24190c3](https://github.com/trozzelle/OfflineDAoC-macOS/commit/24190c35fafdc15bf24ff664c02591d5cd306250))
* **pins:** pins and Local pins per game version ([d8586be](https://github.com/trozzelle/OfflineDAoC-macOS/commit/d8586bec49f3bbb05befe0ed74a0ce999e54e7ec))
* **progress:** upgrade into a chosen edition; inspect --json ([3b0b2b3](https://github.com/trozzelle/OfflineDAoC-macOS/commit/3b0b2b30986470bf6474fb385ba83ead7595a17e))
* **server:** the Sluaghbinder world from upstream's edition diff ([57700c6](https://github.com/trozzelle/OfflineDAoC-macOS/commit/57700c6564cf3d6016152c5350ca483ada6a38e7))
* **update:** updates stay within the selected game version ([a8bcf96](https://github.com/trozzelle/OfflineDAoC-macOS/commit/a8bcf96280fe4d108bc32edce8829c19f227333a))


### Bug Fixes

* **client:** daoc client update moves the default client, including the new client ([9de5e34](https://github.com/trozzelle/OfflineDAoC-macOS/commit/9de5e34621106ab70daf68d27f072bf293e88600))
* **e2e:** a fresh save starts as the selected edition ([c13a295](https://github.com/trozzelle/OfflineDAoC-macOS/commit/c13a29562bb3ac24cc701cd4bdd4c5e001ced0e5))
* **e2e:** refuse a server config whose port the client will not use ([cdc18bf](https://github.com/trozzelle/OfflineDAoC-macOS/commit/cdc18bf2c11d38008c816b58bb15fbbb23721a50))
* **game:** restore with no current save, keep a pending switch's client, switch past an unreadable selection ([0aa4918](https://github.com/trozzelle/OfflineDAoC-macOS/commit/0aa491893bce563a85522fb31359905b5663791a))
* restore a set-aside save with its -wal; refuse the new client on a game without one ([c4e680a](https://github.com/trozzelle/OfflineDAoC-macOS/commit/c4e680a23ef2dfc6ed1d84b90a736e4d93059d2f))
* **saves:** read the edition of a restored WAL save without its sidecars ([8b231d9](https://github.com/trozzelle/OfflineDAoC-macOS/commit/8b231d97cc505f4977901d8a14ff49c057720d81))
* **server:** build 0.36 and 0.35 from per-version patches and navmesh sets ([23bdf7c](https://github.com/trozzelle/OfflineDAoC-macOS/commit/23bdf7ce7cc6f470ac984c394df7a6137ad18d49))
* **server:** log logins again on 0.36 (lazy LoginRequestHandler logger) ([e5787ed](https://github.com/trozzelle/OfflineDAoC-macOS/commit/e5787edb642b60ed20f638fb85d43d9dbd14d913))

## [0.2.0](https://github.com/trozzelle/OfflineDAoC-macOS/compare/v0.1.1...v0.2.0) (2026-10-12)


### Features

* **client:** opt-in arm64 Wine with FEX (no Rosetta) ([f216953](https://github.com/trozzelle/OfflineDAoC-macOS/commit/f216953982feeb1a073fdb7a5ef192afa06a6aa7))
* **client:** opt-in arm64 Wine with FEX (no Rosetta) ([ee6ef8d](https://github.com/trozzelle/OfflineDAoC-macOS/commit/ee6ef8d519f9b06997c1af8f34b97ed839628320))


### Bug Fixes

* **client:** address PR review on the arm64 Wine install ([e6cfc8b](https://github.com/trozzelle/OfflineDAoC-macOS/commit/e6cfc8b84f231982a15ddc58d285b7ef619765a9))
* **client:** one arm64 Wine test and env for every wine daoc runs ([17ad8df](https://github.com/trozzelle/OfflineDAoC-macOS/commit/17ad8dfd7550b4cea7163a3f3defe02549577ceb))
* **client:** run the arm64 Wine with FEX x87 reduced precision ([35b1eb6](https://github.com/trozzelle/OfflineDAoC-macOS/commit/35b1eb6dd0a80538438fa7716094f534726796e0))

## [0.1.1](https://github.com/trozzelle/OfflineDAoC-macOS/compare/v0.1.0...v0.1.1) (2026-10-12)


### Bug Fixes

* **client:** refuse client install below macOS 26 ([b35759f](https://github.com/trozzelle/OfflineDAoC-macOS/commit/b35759f8456c989c45a9c7238791490e07c4a032))
* **client:** take the macOS minimum from the Wine pin ([42e876b](https://github.com/trozzelle/OfflineDAoC-macOS/commit/42e876b03ea66e6c4de2ce397481d029da21e999))

## 0.1.0 (2026-10-12)


### Features

* versioned releases with release-please and daoc --version ([53d3ac6](https://github.com/trozzelle/OfflineDAoC-macOS/commit/53d3ac6bb07681f4a9e6a4a0f194e12da94797c6))
