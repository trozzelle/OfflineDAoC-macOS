# Universal: wine runs x86_64 under Rosetta; x87sidecar (arm64) inherits
# DYLD_INSERT_LIBRARIES too and must be able to load it.
ftlog.dylib: ftlog.m
	clang -arch x86_64 -arch arm64 -dynamiclib -fobjc-arc -O2 -mmacosx-version-min=13.0 \
		-framework QuartzCore -framework Foundation -o $@ $<
