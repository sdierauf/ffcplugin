return {
    LrSdkVersion = 6.0,
    LrSdkMinimumVersion = 3.0,

    LrToolkitIdentifier = "com.sdierauf.lightroom-flatfield-stager",
    LrPluginName = "Flat Field Correction",

    LrPluginInfoProvider = "PluginInfoProvider.lua",

    LrLibraryMenuItems = {
        {
            title = "Flat Field Correction...",
            file = "FlatFieldCorrection.lua",
        },
    },

    VERSION = {
        major = 0,
        minor = 1,
        revision = 0,
        build = 1,
    },
}
