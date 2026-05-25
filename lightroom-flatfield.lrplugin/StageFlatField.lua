local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrFileUtils = import "LrFileUtils"
local LrPathUtils = import "LrPathUtils"
local LrProgressScope = import "LrProgressScope"
local LrTasks = import "LrTasks"

local Settings = require "Settings"

local function trim(value)
    if value == nil then
        return ""
    end

    return tostring(value):match("^%s*(.-)%s*$")
end

local function isWindows()
    if package and package.config and package.config:sub(1, 1) == "\\" then
        return true
    end

    local pluginPath = (_PLUGIN and _PLUGIN.path) or ""
    return pluginPath:match("^%a:[/\\]") ~= nil or pluginPath:find("\\", 1, true) ~= nil
end

local function shellQuote(arg)
    arg = tostring(arg or "")

    if isWindows() then
        return '"' .. arg:gsub('"', '\\"') .. '"'
    end

    return "'" .. arg:gsub("'", "'\\''") .. "'"
end

local function commandPrefix(command)
    command = trim(command)

    if command == "" then
        command = Settings.defaultPythonCommand()
    end

    if command:find("/", 1, true) or command:find("\\", 1, true) or command:match("^%a:") then
        return shellQuote(command)
    end

    return command
end

local function writeTextFile(path, text)
    local file, err = io.open(path, "wb")
    if not file then
        return nil, err
    end

    file:write(text)
    file:close()
    return true
end

local function readTextFile(path)
    local file = io.open(path, "rb")
    if not file then
        return nil
    end

    local text = file:read("*a")
    file:close()
    return text
end

local function urlDecode(value)
    value = tostring(value or "")
    value = value:gsub("+", " ")
    return (value:gsub("%%(%x%x)", function(hex)
        return string.char(tonumber(hex, 16))
    end))
end

local function parseResult(text)
    local result = {}

    for line in tostring(text or ""):gmatch("[^\r\n]+") do
        local key, value = line:match("^([^=]+)=(.*)$")
        if key then
            result[key] = urlDecode(value)
        end
    end

    return result
end

local function tempPath(suffix)
    local tempDir = LrPathUtils.getStandardFilePath("temp")
    local name = "ffcplugin-" .. tostring(os.time()) .. "-" .. tostring(math.random(100000, 999999)) .. suffix
    return LrPathUtils.child(tempDir, name)
end

local function chooseCalibrationPath()
    local result = LrDialogs.runOpenPanel {
        title = "Choose flat-field calibration raw",
        prompt = "Choose",
        canChooseFiles = true,
        canChooseDirectories = false,
        allowsMultipleSelection = false,
    }

    if result and result[1] then
        return result[1]
    end

    return nil
end

local function getSelectedPhotos(catalog)
    local activePhoto = catalog:getTargetPhoto()
    if not activePhoto then
        return {}
    end

    local photos = catalog:getTargetPhotos()

    if not photos or #photos == 0 then
        photos = { activePhoto }
    end

    return photos or {}
end

local function getPhotoPaths(photos)
    local paths = {}

    for _, photo in ipairs(photos) do
        local ok, path = LrTasks.pcall(function()
            return photo:getRawMetadata("path")
        end)

        if ok and path and path ~= "" then
            table.insert(paths, path)
        end
    end

    return paths
end

local function getActiveSources(catalog)
    local ok, sources = LrTasks.pcall(function()
        return catalog:getActiveSources()
    end)

    if not ok or not sources then
        return {}
    end

    if type(sources) ~= "table" then
        return { sources }
    end

    return sources
end

local function sourceType(source)
    if type(source) == "string" then
        return source
    end

    local ok, value = LrTasks.pcall(function()
        return source:type()
    end)

    if ok then
        return value
    end

    return nil
end

local function sourceName(source)
    if type(source) == "string" then
        return source
    end

    local ok, value = LrTasks.pcall(function()
        return source:getName()
    end)

    if ok and value then
        return value
    end

    return tostring(source)
end

local function addStagedPhotoToActiveSources(activeSources, stagedPhoto)
    local addedCount = 0
    local warnings = {}

    for _, source in ipairs(activeSources or {}) do
        local kind = sourceType(source)

        if kind == "LrCollection" or kind == "LrPublishedCollection" then
            local okSmart, isSmart = LrTasks.pcall(function()
                return source:isSmartCollection()
            end)

            if okSmart and isSmart then
                table.insert(warnings, "The active source '" .. sourceName(source) .. "' is a smart collection, so Lightroom cannot manually add the staged calibration frame to it.")
            else
                local okAdd, addErr = LrTasks.pcall(function()
                    source:addPhotos({ stagedPhoto })
                end)

                if okAdd then
                    addedCount = addedCount + 1
                else
                    table.insert(warnings, "Could not add the staged calibration frame to '" .. sourceName(source) .. "': " .. tostring(addErr))
                end
            end
        elseif kind == "LrCollectionSet" or kind == "LrPublishedCollectionSet" then
            table.insert(warnings, "The active source '" .. sourceName(source) .. "' is a collection set, which cannot directly contain photos. Select a regular collection or folder before staging if you need the calibration frame visible there.")
        end
    end

    return addedCount, warnings
end

local function appendWarnings(target, values)
    for _, value in ipairs(values or {}) do
        table.insert(target, value)
    end
end

local function buildCommand(settings, calibrationPath, selectedListPath, resultPath)
    local parts = {
        commandPrefix(settings.pythonCommand),
        shellQuote(settings.helperScriptPath),
        "--calibration",
        shellQuote(calibrationPath),
        "--selected-list",
        shellQuote(selectedListPath),
        "--result-file",
        shellQuote(resultPath),
    }

    if trim(settings.exiftoolPath) ~= "" then
        table.insert(parts, "--exiftool")
        table.insert(parts, shellQuote(settings.exiftoolPath))
    end

    return table.concat(parts, " ")
end

local function importStagedPhoto(catalog, stagedPath, activeSources)
    local stagedPhoto = nil
    local addedCount = 0
    local warnings = {}

    local ok, err = LrTasks.pcall(function()
        catalog:withWriteAccessDo("Import flat-field calibration frame", function()
            stagedPhoto = catalog:findPhotoByPath(stagedPath)
            if not stagedPhoto then
                stagedPhoto = catalog:addPhoto(stagedPath)
            end

            if stagedPhoto then
                addedCount, warnings = addStagedPhotoToActiveSources(activeSources, stagedPhoto)
            end
        end)
    end)

    if not ok then
        return nil, err
    end

    if not stagedPhoto then
        return nil, "Lightroom did not return a catalog photo for " .. stagedPath
    end

    return stagedPhoto, nil, addedCount, warnings
end

local function restoreActiveSources(catalog, activeSources)
    if not activeSources or #activeSources == 0 then
        return nil
    end

    local ok, result = LrTasks.pcall(function()
        return catalog:setActiveSources(activeSources)
    end)

    if not ok or result == false then
        return "The staged frame was imported, but Lightroom did not restore the previous active source."
    end

    return nil
end

local function selectOriginalsAndCalibration(catalog, originalPhotos, stagedPhoto)
    local activePhoto = originalPhotos[1]
    local ok, targetPhoto = LrTasks.pcall(function()
        return catalog:getTargetPhoto()
    end)

    if ok and targetPhoto then
        for _, photo in ipairs(originalPhotos) do
            if photo == targetPhoto then
                activePhoto = targetPhoto
                break
            end
        end
    end

    local others = {}
    for _, photo in ipairs(originalPhotos) do
        if photo ~= activePhoto then
            table.insert(others, photo)
        end
    end
    table.insert(others, stagedPhoto)

    catalog:setSelectedPhotos(activePhoto, others)
end

local function cleanup(paths)
    for _, path in ipairs(paths) do
        if path then
            LrTasks.pcall(function()
                LrFileUtils.delete(path)
            end)
        end
    end
end

local function fail(message)
    error(message, 0)
end

local function run()
    local tempFiles = {}
    local progressScope = LrProgressScope {
        title = "Staging flat-field calibration",
    }

    local ok, err = LrTasks.pcall(function()
        progressScope:setCaption("Reading selected photos")
        progressScope:setPortionComplete(0, 6)
        local catalog = LrApplication.activeCatalog()
        local photos = getSelectedPhotos(catalog)

        if #photos == 0 then
            fail("Select one or more scan photos before staging a calibration frame.")
        end

        local photoPaths = getPhotoPaths(photos)
        if #photoPaths == 0 then
            fail("Lightroom did not provide filesystem paths for the selected photos.")
        end

        local calibrationPath = chooseCalibrationPath()
        if not calibrationPath then
            return
        end

        progressScope:setCaption("Preparing staging helper")
        progressScope:setPortionComplete(1, 6)
        local settings = Settings.effective()
        local activeSources = getActiveSources(catalog)
        if not Settings.pathExists(settings.helperScriptPath) then
            fail("The helper script was not found:\n\n" .. settings.helperScriptPath .. "\n\nUse Configure Flat-Field Stager to choose scripts/stage_calibration.py.")
        end

        local selectedListPath = tempPath("-selected.txt")
        local resultPath = tempPath("-result.txt")
        table.insert(tempFiles, selectedListPath)
        table.insert(tempFiles, resultPath)

        local wrote, writeErr = writeTextFile(selectedListPath, table.concat(photoPaths, "\n") .. "\n")
        if not wrote then
            fail("Could not write selected-photo list: " .. tostring(writeErr))
        end

        progressScope:setCaption("Copying and timestamping calibration frame")
        progressScope:setPortionComplete(2, 6)
        local exitCode = LrTasks.execute(buildCommand(settings, calibrationPath, selectedListPath, resultPath))
        local result = parseResult(readTextFile(resultPath))

        if exitCode ~= 0 or result.status ~= "ok" then
            fail(result.message ~= "" and result.message or "The staging helper failed.")
        end

        local stagedPath = result.staged_path
        if not stagedPath or stagedPath == "" then
            fail("The staging helper did not report a staged calibration path.")
        end

        progressScope:setCaption("Importing staged calibration frame")
        progressScope:setPortionComplete(3, 6)
        local stagedPhoto, importErr, addedSourceCount, sourceWarnings = importStagedPhoto(catalog, stagedPath, activeSources)
        if not stagedPhoto then
            fail("The calibration copy was staged, but Lightroom could not import it:\n\n" .. tostring(importErr))
        end

        progressScope:setCaption("Selecting originals and staged calibration frame")
        progressScope:setPortionComplete(4, 6)
        local restoreWarning = restoreActiveSources(catalog, activeSources)
        selectOriginalsAndCalibration(catalog, photos, stagedPhoto)
        progressScope:setCaption("Flat-field calibration staged")
        progressScope:setPortionComplete(6, 6)

        local warning = trim(result.warning)
        local warningLines = {}
        if warning ~= "" then
            table.insert(warningLines, warning)
        end
        appendWarnings(warningLines, sourceWarnings)
        if restoreWarning then
            table.insert(warningLines, restoreWarning)
        end

        local message = "Staged and imported:\n" .. stagedPath
        if addedSourceCount and addedSourceCount > 0 then
            message = message .. "\n\nAdded the staged frame to " .. tostring(addedSourceCount) .. " active Lightroom collection source(s)."
        end
        message = message .. "\n\nThe original scans and the staged calibration frame are selected. Now run Library > Flat-Field Correction."
        local style = "info"

        if #warningLines > 0 then
            message = message .. "\n\nWarning: " .. table.concat(warningLines, "\n")
            style = "warning"
        end

        LrDialogs.message("Flat-Field calibration staged", message, style)
    end)

    cleanup(tempFiles)
    LrTasks.pcall(function()
        progressScope:done()
    end)

    if not ok then
        LrDialogs.message("Flat-Field Stager", tostring(err), "critical")
    end
end

LrTasks.startAsyncTask(run, "Stage Flat-Field Calibration Frame")
