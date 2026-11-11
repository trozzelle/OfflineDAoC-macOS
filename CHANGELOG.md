# Changelog

## [0.5.0](https://github.com/trozzelle/OfflineDAoC-macOS/compare/v0.4.0...v0.5.0) (2026-11-11)


### Features

* ./daoc runs a bundled Python beside its code root ([b00e770](https://github.com/trozzelle/OfflineDAoC-macOS/commit/b00e7703c4b698448a13a995f88ad25ddfab375d))
* a data home apart from the code root (DAOC_DATA) ([18ea83d](https://github.com/trozzelle/OfflineDAoC-macOS/commit/18ea83df0e37d1896f1f26ea9da347a081e0c861))
* **app:** app model, sheets, self-test and quit handling ([8a78ea7](https://github.com/trozzelle/OfflineDAoC-macOS/commit/8a78ea7eb9816adad549d14d6cdcebd6ea20cb4d))
* **app:** launcher with Play, server, bots, settings and updates ([bf77694](https://github.com/trozzelle/OfflineDAoC-macOS/commit/bf776946f9bc04cbc9176703389dd66feee8dadf))
* **app:** run daoc with an event pipe, answers and a log ([312c673](https://github.com/trozzelle/OfflineDAoC-macOS/commit/312c6739952dad1fec8e651ab6580a9c5a87109f))
* **app:** Setup wizard ([a3f9abb](https://github.com/trozzelle/OfflineDAoC-macOS/commit/a3f9abb90d35ebf2b2b81679bef7c64aacbeee3a))
* **app:** status, bots, Setup plan and release models ([f9064e9](https://github.com/trozzelle/OfflineDAoC-macOS/commit/f9064e936f08b72a5fd6d94d9158aa6966533eda))
* **app:** Swift package with the daoc event protocol ([ae3ac8a](https://github.com/trozzelle/OfflineDAoC-macOS/commit/ae3ac8a02b1274e9284d12bcb45d6abb2e95c1f7))
* **client:** the app saves the game account through a secret event ([4fd89c2](https://github.com/trozzelle/OfflineDAoC-macOS/commit/4fd89c2d26e9f56de83b85676a40df6bd9b20794))
* daoc status --json for the OfflineDAoC app ([b68c90d](https://github.com/trozzelle/OfflineDAoC-macOS/commit/b68c90d4748706d8ef6ba27080fc5ebb063a0b70))
* **dev:** pack-server and ship-prebuilt for the prebuilt server ([ce4fd2f](https://github.com/trozzelle/OfflineDAoC-macOS/commit/ce4fd2fbb007ca6beebab06aa2918e87187244c5))
* download events name the file growing on disk ([7c80c20](https://github.com/trozzelle/OfflineDAoC-macOS/commit/7c80c2096c62dce13571e1215ea1282774a006b3))
* JSON event channel for the OfflineDAoC app (DAOC_EVENTS) ([b74ea28](https://github.com/trozzelle/OfflineDAoC-macOS/commit/b74ea28b4040954aeba6217e668a61af6b4e08d0))
* OfflineDAoC.app, a one-click installer and launcher for macOS ([90dc933](https://github.com/trozzelle/OfflineDAoC-macOS/commit/90dc933fac6e770213fb8a99e53b7a8578e980b5))
* **server:** --from-source, and Local pins never carry a prebuilt ([de645ea](https://github.com/trozzelle/OfflineDAoC-macOS/commit/de645ea39809439a8dcf0a148d63e5dadc283cbe))
* **server:** install a pinned prebuilt server without a build toolchain ([4a7f637](https://github.com/trozzelle/OfflineDAoC-macOS/commit/4a7f637165179488da288cee87c979a2b810b6a3))
* **server:** pin the prebuilt 0.37 server; app/dev-run.sh runs the app on a test data folder ([73e5d03](https://github.com/trozzelle/OfflineDAoC-macOS/commit/73e5d0301a426daf049adc622fc47c95bd3d565b))
* **server:** start --detach returns once the server is ready ([97e1922](https://github.com/trozzelle/OfflineDAoC-macOS/commit/97e19223f0e338daf947bcb5f8eb3fd52ce939be))


### Bug Fixes

* **app:** a Keychain account from another install does not skip Setup's account step ([1db992c](https://github.com/trozzelle/OfflineDAoC-macOS/commit/1db992c0baf9fe7d399af6952a1624711f085e2e))
* **app:** a late answer never raises SIGPIPE; interrupt before spawn is kept ([6070e7d](https://github.com/trozzelle/OfflineDAoC-macOS/commit/6070e7d560bc16b26a01b44a1502d774d7b60315))
* **app:** Escape always answers No in the ask sheet ([8492191](https://github.com/trozzelle/OfflineDAoC-macOS/commit/84921919591a12760f6e4249ed892b2c8a504b6e))
* **app:** Install daoc Command is disabled while another command runs ([9ed04de](https://github.com/trozzelle/OfflineDAoC-macOS/commit/9ed04de96729e894382d47bf0d81f6370763833a))
* **app:** launcher settings match what the CLI accepts ([8b95e93](https://github.com/trozzelle/OfflineDAoC-macOS/commit/8b95e933402f5cd64e95a9f69b713a4870d51073))
* **app:** quit confirms before stopping work; one window; logged server stop ([6e53b5b](https://github.com/trozzelle/OfflineDAoC-macOS/commit/6e53b5bb2fc516a8a0594f6d12341add8176e674))
* **app:** Setup resumes from the install's status ([3d0f9e6](https://github.com/trozzelle/OfflineDAoC-macOS/commit/3d0f9e6e5226f463a069d2e114df6cdd792405c4))
* **app:** Stop and quit stop treating a finished download as running ([1fc3b94](https://github.com/trozzelle/OfflineDAoC-macOS/commit/1fc3b94f8e2fd37018c5b0a4007c504e0d2c5ff8))
* **app:** the signed bundle never gains .pyc files; build precompiles, the bundled launcher runs python -B ([d221392](https://github.com/trozzelle/OfflineDAoC-macOS/commit/d2213922286a3a9b705963e2447bb44a359f34bb))
* **client:** curl downloads through a .part file so an interrupted one is fetched again ([abdd02c](https://github.com/trozzelle/OfflineDAoC-macOS/commit/abdd02c9bfec8365cbfcc89e31a66b035b31b86f))
* **server:** a short admin socket when its path is too long for macOS ([b28474a](https://github.com/trozzelle/OfflineDAoC-macOS/commit/b28474afc65b3cfeb1cbe7508b7e077683b440ce))
* **server:** prebuilt swap records the pin last; user folders refused in any case ([a7676ae](https://github.com/trozzelle/OfflineDAoC-macOS/commit/a7676aeb5a20ba77a0be6fc7c4d44a8d668b45a8))
* **server:** start --detach refuses a daoc-server.sh that predates it instead of hanging ([c4c130c](https://github.com/trozzelle/OfflineDAoC-macOS/commit/c4c130c06eca10a751456856d05cef7cb4024378))
* **server:** start --detach waits for a server that is already starting ([d5d5dbb](https://github.com/trozzelle/OfflineDAoC-macOS/commit/d5d5dbbe7a3824cf56947c2f39457135780856db))
* **server:** the fallback admin socket lives in the per-user temp folder ([4ce19f5](https://github.com/trozzelle/OfflineDAoC-macOS/commit/4ce19f5e2af8c9032a1cae05a270c7893d53d767))
* **status:** the original client counts as installed once client install has recorded its flavour ([85dd036](https://github.com/trozzelle/OfflineDAoC-macOS/commit/85dd036b9987ce5f7e7ed0086c68d92fa5e822ea))
* wine tools get no stdin in event mode ([c1b4d33](https://github.com/trozzelle/OfflineDAoC-macOS/commit/c1b4d3378bb80677a08cf58ed1afb8bdd7a28796))

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
