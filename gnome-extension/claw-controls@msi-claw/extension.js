import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as KeyboardUI from 'resource:///org/gnome/shell/ui/keyboard.js';
import * as IBusManager from 'resource:///org/gnome/shell/misc/ibusManager.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const DBUS_IFACE = `
<node>
  <interface name="org.gnome.Shell.Extensions.ClawControls">
    <method name="ToggleOSK"/>
    <method name="OpenOSK"/>
    <method name="CloseOSK"/>
    <method name="ToggleOverview"/>
    <method name="ShowApps"/>
    <method name="ToggleQuickSettings"/>
    <method name="ShowOSD">
      <arg type="s" direction="in" name="icon"/>
      <arg type="s" direction="in" name="label"/>
    </method>
    <method name="SetControllerMode">
      <arg type="s" direction="in" name="mode"/>
    </method>
  </interface>
</node>`;

// Shared override implementations (one function object each, so repeated hook calls stay idempotent)
function clawKeyvalPress(keyval) {
    this._virtualDevice.notify_keyval(GLib.get_monotonic_time(), keyval, Clutter.KeyState.PRESSED);
}

function clawKeyvalRelease(keyval) {
    this._virtualDevice.notify_keyval(GLib.get_monotonic_time(), keyval, Clutter.KeyState.RELEASED);
}

function clawSetRatio() {
    this._ratio = 10;
    this.queue_relayout();
}

function clawLastDeviceIsTouchscreen() {
    return true;
}

function clawMaybeHandleEvent(event) {
    if (!this._keyboard)
        return false;
    const actor = global.stage.get_event_actor(event);
    if (!actor)
        return false;
    if (Main.layoutManager.keyboardBox.contains(actor) ||
        !!actor._extendedKeys || !!actor.extendedKey) {
        actor.event(event, true);
        actor.event(event, false);
        return true;
    }
    return false;
}

const ClawPanelButton = GObject.registerClass(
class ClawPanelButton extends PanelMenu.Button {
    _init(ext) {
        super._init(0.0, 'MSI Claw Controls', false);
        this._ext = ext;
        this._destroyed = false;
        this._tempPath = null;
        this._fanPath = null;

        this.connect('destroy', () => {
            this._destroyed = true;
        });

        this._box = new St.BoxLayout({
            style_class: 'panel-status-indicators-box',
        });

        this._icon = new St.Icon({
            icon_name: 'input-mouse-symbolic',
            style_class: 'system-status-icon',
        });
        this._box.add_child(this._icon);
        this.add_child(this._box);

        // Live telemetry row — updated ONLY when the menu opens (0% idle overhead)
        this._telemetryItem = new PopupMenu.PopupMenuItem('BAT --% · --°C · -- RPM', {
            reactive: false,
            can_focus: false,
            style_class: 'claw-telemetry-item',
        });
        this._telemetryItem.label.add_style_class_name('claw-telemetry-item');
        this.menu.addMenuItem(this._telemetryItem);

        this._openCenterItem = new PopupMenu.PopupMenuItem('Open MSI Claw Center (GUI)');
        this._openCenterItem.connect('activate', () => {
            try {
                Gio.Subprocess.new(
                    [`${GLib.get_home_dir()}/.local/bin/msi-claw-center`, '--toggle'],
                    Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
                );
            } catch (e) {
                console.error('ClawControls: Failed to launch MSI Claw Center:', e);
            }
        });
        this.menu.addMenuItem(this._openCenterItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Handheld Power Profile Controls
        this._powerItems = new Map();
        const powerProfiles = [
            ['power-saver', 'Power: Power Saver (Max Battery)', 'power-profile-power-saver-symbolic', 'Power Profile: Power Saver'],
            ['balanced', 'Power: Balanced', 'power-profile-balanced-symbolic', 'Power Profile: Balanced'],
            ['performance', 'Power: Performance (Max TDP)', 'power-profile-performance-symbolic', 'Power Profile: Performance'],
        ];
        for (const [profile, title, iconName, osdLabel] of powerProfiles) {
            const item = new PopupMenu.PopupMenuItem(title);
            item.connect('activate', () => {
                this._ext._setPowerProfile(profile);
                this._ext.ShowOSD(iconName, osdLabel);
            });
            this.menu.addMenuItem(item);
            this._powerItems.set(profile, item);
        }

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Display Refresh Rate + VRR Controls
        this._hz60Item = new PopupMenu.PopupMenuItem('Display: 60 Hz + VRR (Save ~1.5W)');
        this._hz60Item.connect('activate', () => {
            this._ext._setRefreshRate(60);
            this._ext.ShowOSD('video-display-symbolic', 'Display: 60 Hz + VRR');
        });
        this.menu.addMenuItem(this._hz60Item);

        this._hz120Item = new PopupMenu.PopupMenuItem('Display: 120 Hz + VRR (Smooth Gaming)');
        this._hz120Item.connect('activate', () => {
            this._ext._setRefreshRate(120);
            this._ext.ShowOSD('video-display-symbolic', 'Display: 120 Hz + VRR');
        });
        this.menu.addMenuItem(this._hz120Item);

        this._autoSwitchItem = new PopupMenu.PopupSwitchMenuItem(
            'Auto-Switch Power & RGB on AC/Battery',
            this._ext._autoPowerSwitch
        );
        this._autoSwitchItem.connect('toggled', (_item, state) => {
            this._ext._autoPowerSwitch = state;
        });
        this.menu.addMenuItem(this._autoSwitchItem);

        // Controller RGB Power Controls (hhd / claw-ambient zero-flash-wear HID protocol)
        this._rgbSubMenu = new PopupMenu.PopupSubMenuMenuItem('Controller RGB Lighting');
        for (const [mode, label] of [
            ['off', 'RGB Off (Save ~0.8W Battery)'],
            ['dim', 'RGB Dim Cyan (15%)'],
            ['on', 'RGB MSI Red (75%)'],
        ]) {
            const rgbItem = new PopupMenu.PopupMenuItem(label);
            rgbItem.connect('activate', () => {
                this._ext._setControllerRGB(mode);
                this._ext.ShowOSD('input-gaming-symbolic', `Controller ${label}`);
            });
            this._rgbSubMenu.menu.addMenuItem(rgbItem);
        }
        this.menu.addMenuItem(this._rgbSubMenu);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Handheld Mode, OSK & App Grid Actions
        this._modeItem = new PopupMenu.PopupMenuItem('Mode: Desktop Control (Switch to Gamepad)');
        this._modeItem.connect('activate', () => {
            this._ext.requestModeToggle();
        });
        this.menu.addMenuItem(this._modeItem);
        this.updateMode(this._ext._controllerMode);

        this._oskItem = new PopupMenu.PopupMenuItem('Toggle On-Screen Keyboard (OSK)');
        this._oskItem.connect('activate', () => {
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
                this._ext.ToggleOSK();
                return GLib.SOURCE_REMOVE;
            });
        });
        this.menu.addMenuItem(this._oskItem);

        this._appsItem = new PopupMenu.PopupMenuItem('Open Applications / Overview');
        this._appsItem.connect('activate', () => {
            this._ext.ShowApps();
        });
        this.menu.addMenuItem(this._appsItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Collapsible Controller Shortcuts Reference
        this._guideSubMenu = new PopupMenu.PopupSubMenuMenuItem('MSI Claw Desktop Controls');
        const mappings = [
            'L-Stick: Move Mouse  |  R-Stick: Scroll',
            'A / RT: Left Click   |  B: Right Click',
            'X: On-Screen Kbd     |  Y: App Overview',
            'D-Pad: Arrow Keys    |  Menu: Alt+Tab Switch',
            'LB / RB: Back / Fwd  |  LT: Slow Mouse',
            'L3: Middle Click     |  R3: Backspace',
            'View + Menu: Toggle Desktop/Gamepad Mode',
            'View + D-Pad Up/Dn: Volume Up/Down',
            'View + D-Pad Lt/Rt: Brightness Down/Up',
            'MSI Button (L): Apps | Quick Btn (R): Quick Settings',
        ];
        for (const line of mappings) {
            const item = new PopupMenu.PopupMenuItem(line, {
                reactive: false,
                can_focus: false,
            });
            this._guideSubMenu.menu.addMenuItem(item);
        }
        this.menu.addMenuItem(this._guideSubMenu);

        this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen)
                this._refreshTelemetry();
        });
    }

    _readSysfsText(path) {
        try {
            const [ok, bytes] = GLib.file_get_contents(path);
            if (!ok || !bytes)
                return null;
            return new TextDecoder('utf-8').decode(bytes).trim();
        } catch (_e) {
            return null;
        }
    }

    _resolveHwmonPaths() {
        if (this._tempPath && GLib.file_test(this._tempPath, GLib.FileTest.EXISTS) &&
            this._fanPath && GLib.file_test(this._fanPath, GLib.FileTest.EXISTS)) {
            return;
        }

        let cpuTemp = null;
        let fallbackTemp = null;
        let msiFan = null;
        let fallbackFan = null;

        try {
            const dir = Gio.File.new_for_path('/sys/class/hwmon');
            const iter = dir.enumerate_children(
                'standard::name',
                Gio.FileQueryInfoFlags.NONE,
                null
            );
            let info;
            while ((info = iter.next_file(null)) !== null) {
                const base = `/sys/class/hwmon/${info.get_name()}`;
                const name = this._readSysfsText(`${base}/name`);
                const t1 = `${base}/temp1_input`;
                const f1 = `${base}/fan1_input`;

                if (name === 'coretemp' && GLib.file_test(t1, GLib.FileTest.EXISTS))
                    cpuTemp = t1;
                else if (name === 'acpitz' && !fallbackTemp && GLib.file_test(t1, GLib.FileTest.EXISTS))
                    fallbackTemp = t1;

                if (name === 'msi_wmi_platform' && GLib.file_test(f1, GLib.FileTest.EXISTS))
                    msiFan = f1;
                else if (!fallbackFan && GLib.file_test(f1, GLib.FileTest.EXISTS))
                    fallbackFan = f1;
            }
            iter.close(null);
        } catch (_e) {
            // Fall back to known MSI Claw A1M sysfs paths below
        }

        this._tempPath = cpuTemp || fallbackTemp || '/sys/class/hwmon/hwmon5/temp1_input';
        this._fanPath = msiFan || fallbackFan || '/sys/class/hwmon/hwmon4/fan1_input';
    }

    _refreshTelemetry() {
        try {
            this._resolveHwmonPaths();

            const batBase = '/sys/class/power_supply/BAT1';
            const cap = this._readSysfsText(`${batBase}/capacity`) ?? '--';
            const status = this._readSysfsText(`${batBase}/status`) ?? 'Unknown';
            const powerNowStr = this._readSysfsText(`${batBase}/power_now`);
            let watts = 0;
            if (powerNowStr !== null) {
                watts = Math.abs(parseFloat(powerNowStr)) / 1e6;
            } else {
                const cur = parseFloat(this._readSysfsText(`${batBase}/current_now`) ?? '0');
                const volt = parseFloat(this._readSysfsText(`${batBase}/voltage_now`) ?? '0');
                if (Number.isFinite(cur) && Number.isFinite(volt))
                    watts = (Math.abs(cur) * volt) / 1e12;
            }

            const tempMilli = parseFloat(this._readSysfsText(this._tempPath) ?? 'NaN');
            const tempStr = Number.isFinite(tempMilli)
                ? `${Math.round(tempMilli / 1000)}°C`
                : '--°C';

            const fanRpm = parseInt(this._readSysfsText(this._fanPath) ?? 'NaN', 10);
            const fanStr = Number.isFinite(fanRpm) ? `${fanRpm} RPM` : '-- RPM';

            const statusDetail = Number.isFinite(watts) && watts >= 0.1
                ? `${status} ${watts.toFixed(1)}W`
                : status;

            this._telemetryItem.label.text =
                `BAT ${cap}% (${statusDetail}) · ${tempStr} · ${fanStr}`;

            this._refreshActiveOrnaments();
        } catch (e) {
            console.error('ClawControls: Error refreshing telemetry:', e);
        }
    }

    _refreshActiveOrnaments() {
        Gio.DBus.system.call(
            'org.freedesktop.UPower.PowerProfiles',
            '/org/freedesktop/UPower/PowerProfiles',
            'org.freedesktop.DBus.Properties',
            'Get',
            new GLib.Variant('(ss)', ['org.freedesktop.UPower.PowerProfiles', 'ActiveProfile']),
            GLib.VariantType.new('(v)'),
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (conn, res) => {
                try {
                    const reply = conn.call_finish(res);
                    if (this._destroyed)
                        return;
                    const [active] = reply.recursiveUnpack();
                    for (const [profile, item] of this._powerItems.entries()) {
                        item.setOrnament(
                            profile === active
                                ? PopupMenu.Ornament.DOT
                                : PopupMenu.Ornament.NO_DOT
                        );
                    }
                } catch (_e) {
                    // Ignore if power-profiles-daemon is unavailable
                }
            }
        );

        try {
            const proc = Gio.Subprocess.new(
                ['gdctl', 'show'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
            );
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    const [, stdout] = p.communicate_utf8_finish(res);
                    if (this._destroyed || !stdout)
                        return;
                    const modeMatch = stdout.match(/Current mode[\s\S]*?@([0-9.]+)/);
                    if (modeMatch?.[1]) {
                        const hz = parseFloat(modeMatch[1]);
                        const is60 = hz < 90;
                        this._hz60Item.setOrnament(
                            is60 ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NO_DOT
                        );
                        this._hz120Item.setOrnament(
                            !is60 ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NO_DOT
                        );
                    }
                } catch (_e) {
                    // Ignore gdctl query errors
                }
            });
        } catch (_e) {
            // Ignore if gdctl is unavailable
        }
    }

    updateMode(mode) {
        if (mode === 'gamepad') {
            this._icon.icon_name = 'input-gaming-symbolic';
            this._modeItem.label.text = 'Mode: Gamepad (Switch to Desktop Control)';
        } else {
            this._icon.icon_name = 'input-mouse-symbolic';
            this._modeItem.label.text = 'Mode: Desktop Control (Switch to Gamepad)';
        }
    }
});

export default class ClawControlsExtension extends Extension {
    enable() {
        this._controllerMode = this._readInitialControllerMode();
        this._autoPowerSwitch = true;
        this._lastOnBattery = null;
        this._upowerSignalId = 0;
        this._login1SignalId = 0;
        this._resumeTimerIds = new Set();

        this._fixTouchscreenAndOSK();
        this._enhanceOSKSizeAndLayout();

        this._dbusImpl = Gio.DBusExportedObject.wrapJSObject(DBUS_IFACE, this);
        this._dbusImpl.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/ClawControls');

        if (!Main.sessionMode.isGreeter) {
            this._indicator = new ClawPanelButton(this);
            Main.panel.addToStatusArea('claw-controls', this._indicator);
            // We stay enabled in unlock-dialog for the OSK; never expose power/display/launch controls behind the lock
            const syncLocked = () => {
                if (Main.sessionMode.isLocked)
                    this._indicator.menu?.close?.();
                this._indicator.visible = !Main.sessionMode.isLocked;
            };
            Main.sessionMode.connectObject('updated', syncLocked, this);
            syncLocked();
            this._setupPowerManager();
            this._setupResumeWakeGuard();
        }
    }

    _readInitialControllerMode() {
        try {
            const uidMatch = GLib.get_user_runtime_dir().match(/\/(\d+)$/);
            const uid = uidMatch ? uidMatch[1] : '1000';
            const modePath = `/dev/shm/msi-claw-mode-${uid}`;
            if (GLib.file_test(modePath, GLib.FileTest.EXISTS)) {
                const [ok, bytes] = GLib.file_get_contents(modePath);
                if (ok && bytes) {
                    const txt = new TextDecoder('utf-8').decode(bytes).trim();
                    if (txt === 'gamepad' || txt === 'desktop')
                        return txt;
                }
            }
        } catch (_e) {
            // Fall back to desktop mode
        }
        return 'desktop';
    }

    _forceDisplayPowerOn() {
        Gio.DBus.session.call(
            'org.gnome.Mutter.DisplayConfig',
            '/org/gnome/Mutter/DisplayConfig',
            'org.freedesktop.DBus.Properties',
            'Set',
            new GLib.Variant('(ssv)', [
                'org.gnome.Mutter.DisplayConfig',
                'PowerSaveMode',
                new GLib.Variant('i', 0),
            ]),
            null,
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            null
        );
        try {
            Main.screenShield?._shortLightbox?.hide?.();
        } catch (_e) {
            // Ignore if ScreenShield lightbox is inactive
        }
    }

    _setupResumeWakeGuard() {
        this._login1SignalId = Gio.DBus.system.signal_subscribe(
            'org.freedesktop.login1',
            'org.freedesktop.login1.Manager',
            'PrepareForSleep',
            '/org/freedesktop/login1',
            null,
            Gio.DBusSignalFlags.NONE,
            (_conn, _sender, _path, _iface, _signal, params) => {
                try {
                    const [aboutToSuspend] = params.recursiveUnpack();
                    if (aboutToSuspend)
                        return;
                    this._forceDisplayPowerOn();
                    for (const delayMs of [120, 480]) {
                        const tid = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delayMs, () => {
                            this._resumeTimerIds.delete(tid);
                            this._forceDisplayPowerOn();
                            return GLib.SOURCE_REMOVE;
                        });
                        this._resumeTimerIds.add(tid);
                    }
                } catch (_e) {
                    // Ignore unpack errors
                }
            }
        );
    }

    disable() {
        if (this._upowerSignalId) {
            Gio.DBus.system.signal_unsubscribe(this._upowerSignalId);
            this._upowerSignalId = 0;
        }
        if (this._login1SignalId) {
            Gio.DBus.system.signal_unsubscribe(this._login1SignalId);
            this._login1SignalId = 0;
        }
        if (this._resumeTimerIds) {
            for (const tid of this._resumeTimerIds)
                GLib.Source.remove(tid);
            this._resumeTimerIds.clear();
        }

        Main.layoutManager?.disconnectObject?.(this);
        Main.keyboard?.disconnectObject?.(this);
        Main.sessionMode.disconnectObject(this);

        const kbd = Main.keyboard?._keyboard;

        for (const key of this._capsKeys ?? [])
            key.disconnectObject?.(this);
        this._capsKeys?.clear();
        kbd?._aspectContainer?.disconnectObject?.(this);

        this._restoreOverrides();
        try {
            // Our setRatio forced 10; hand the real ratio back now that stock setRatio is restored
            if (kbd?._currentPage?.getRatio)
                kbd._aspectContainer?.setRatio(...kbd._currentPage.getRatio());
        } catch (e) {
            console.error('ClawControls: Failed to restore OSK aspect ratio:', e);
        }

        if (kbd?._suggestions) {
            for (const child of kbd._suggestions.get_children())
                child.disconnectObject?.(this);
            kbd._suggestions.disconnectObject?.(this);
            kbd._suggestions.show();
        }

        if (this._origRelayout && KeyboardUI.Keyboard?.prototype) {
            KeyboardUI.Keyboard.prototype._relayout = this._origRelayout;
            if (kbd) {
                kbd._relayout = this._origRelayout.bind(kbd);
                kbd._relayout();
            }
            this._origRelayout = null;
        }

        if (this._origNewForUri) {
            Gio.File.new_for_uri = this._origNewForUri;
            this._origNewForUri = null;
        }

        if (this._dbusImpl) {
            this._dbusImpl.unexport();
            this._dbusImpl = null;
        }

        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }

    _setupPowerManager() {
        // Seed initial OnBattery state so only real AC <-> Battery transitions fire auto-switch
        Gio.DBus.system.call(
            'org.freedesktop.UPower',
            '/org/freedesktop/UPower',
            'org.freedesktop.DBus.Properties',
            'Get',
            new GLib.Variant('(ss)', ['org.freedesktop.UPower', 'OnBattery']),
            GLib.VariantType.new('(v)'),
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (conn, res) => {
                try {
                    const reply = conn.call_finish(res);
                    const [onBat] = reply.recursiveUnpack();
                    if (this._lastOnBattery === null)
                        this._lastOnBattery = Boolean(onBat);
                } catch (_e) {
                    // Ignore initial UPower query error
                }
            }
        );

        // Event-driven subscription on UPower PropertiesChanged (0% polling overhead)
        this._upowerSignalId = Gio.DBus.system.signal_subscribe(
            'org.freedesktop.UPower',
            'org.freedesktop.DBus.Properties',
            'PropertiesChanged',
            '/org/freedesktop/UPower',
            'org.freedesktop.UPower',
            Gio.DBusSignalFlags.NONE,
            (_conn, _sender, _path, _iface, _signal, params) => {
                try {
                    const [, changed] = params.recursiveUnpack();
                    if (!changed || !('OnBattery' in changed))
                        return;

                    const onBattery = Boolean(changed.OnBattery);
                    if (this._lastOnBattery === onBattery)
                        return;
                    this._lastOnBattery = onBattery;

                    if (!this._autoPowerSwitch)
                        return;

                    if (onBattery) {
                        this._setPowerProfile('power-saver');
                        this._setControllerRGB('off');
                        this.ShowOSD('battery-good-symbolic', 'Battery Mode: Power Saver · RGB Off');
                    } else {
                        const targetProfile =
                            this._controllerMode === 'gamepad' ? 'performance' : 'balanced';
                        const profileLabel =
                            targetProfile === 'performance' ? 'Performance' : 'Balanced';
                        this._setPowerProfile(targetProfile);
                        this._setControllerRGB('dim');
                        this.ShowOSD('ac-adapter-symbolic', `AC Power: ${profileLabel} · RGB Dim`);
                    }
                } catch (e) {
                    console.error('ClawControls: UPower PropertiesChanged handler error:', e);
                }
            }
        );
    }

    _setControllerRGB(mode) {
        try {
            const rgbBin = `${GLib.get_home_dir()}/.local/bin/msi-claw-rgb`;
            if (!GLib.file_test(rgbBin, GLib.FileTest.EXISTS))
                return;
            Gio.Subprocess.new(
                [rgbBin, mode],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
            );
        } catch (e) {
            console.error('ClawControls: Error setting controller RGB:', e);
        }
    }

    _setPowerProfile(profile) {
        const setVariant = new GLib.Variant('(ssv)', [
            'org.freedesktop.UPower.PowerProfiles',
            'ActiveProfile',
            new GLib.Variant('s', profile),
        ]);
        Gio.DBus.system.call(
            'org.freedesktop.UPower.PowerProfiles',
            '/org/freedesktop/UPower/PowerProfiles',
            'org.freedesktop.DBus.Properties',
            'Set',
            setVariant,
            null,
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (conn, res) => {
                try {
                    conn.call_finish(res);
                } catch (_e) {
                    const legacyVariant = new GLib.Variant('(ssv)', [
                        'net.hadess.PowerProfiles',
                        'ActiveProfile',
                        new GLib.Variant('s', profile),
                    ]);
                    conn.call(
                        'net.hadess.PowerProfiles',
                        '/net/hadess/PowerProfiles',
                        'org.freedesktop.DBus.Properties',
                        'Set',
                        legacyVariant,
                        null,
                        Gio.DBusCallFlags.NONE,
                        -1,
                        null,
                        null
                    );
                }
            }
        );
    }

    _setRefreshRate(hz) {
        try {
            const showProc = Gio.Subprocess.new(
                ['gdctl', 'show'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
            );
            showProc.communicate_utf8_async(null, null, (proc, res) => {
                let scaleStr = '1.25';
                let resStr = '1920x1080';
                try {
                    const [, stdout] = proc.communicate_utf8_finish(res);
                    if (stdout) {
                        const scaleMatch = stdout.match(/Scale:\s*([0-9.]+)/);
                        if (scaleMatch?.[1])
                            scaleStr = scaleMatch[1];
                        const curMatch = stdout.match(/Current mode[\s\S]*?(\d+x\d+)@([0-9.]+)/);
                        if (curMatch?.[1])
                            resStr = curMatch[1];
                    }
                } catch (_e) {
                    // Keep fallback scale/resolution
                }

                const modesProc = Gio.Subprocess.new(
                    ['gdctl', 'show', '--modes'],
                    Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
                );
                modesProc.communicate_utf8_async(null, null, (mProc, mRes) => {
                    let targetMode = hz === 60
                        ? (resStr === '1600x900' ? '1600x900@59.946+vrr' : '1920x1080@60.004+vrr')
                        : (resStr === '1600x900' ? '1600x900@119.948+vrr' : '1920x1080@120.003+vrr');
                    try {
                        const [, mOut] = mProc.communicate_utf8_finish(mRes);
                        if (mOut) {
                            const re = new RegExp(`(${resStr}@([0-9.]+)\\+vrr)`, 'g');
                            let best = null;
                            let bestDiff = Infinity;
                            for (const m of mOut.matchAll(re)) {
                                const rate = parseFloat(m[2]);
                                const diff = Math.abs(rate - hz);
                                if (diff < 2.0 && diff < bestDiff) {
                                    best = m[1];
                                    bestDiff = diff;
                                }
                            }
                            if (best)
                                targetMode = best;
                        }
                    } catch (_e) {
                        // Fall back to known eDP-1 VRR mode
                    }

                    try {
                        Gio.Subprocess.new(
                            [
                                'gdctl', 'set', '--persistent',
                                '--logical-monitor', '--primary', '--scale', scaleStr,
                                '--monitor', 'eDP-1', '--mode', targetMode,
                            ],
                            Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
                        );
                    } catch (err) {
                        console.error('ClawControls: Failed to set refresh rate via gdctl:', err);
                    }
                });
            });
        } catch (e) {
            console.error('ClawControls: Error launching gdctl subprocess:', e);
        }
    }

    _syncSuggestionsVisibility(suggestions) {
        if (!suggestions)
            return;
        const hasVisibleChild = suggestions.get_children().some(child => child.visible);
        if (hasVisibleChild) {
            if (!suggestions.visible)
                suggestions.show();
        } else if (suggestions.visible) {
            suggestions.hide();
        }
    }

    _attachKeyboardInstanceHooks(kbd) {
        if (!kbd)
            return;

        const kc = kbd._keyboardController;
        if (kc) {
            kc._oskCompletionEnabled = false;
            const kcProto = Object.getPrototypeOf(kc);
            this._override(kcProto, 'keyvalPress', clawKeyvalPress);
            this._override(kcProto, 'keyvalRelease', clawKeyvalRelease);
        }

        if (kbd._aspectContainer) {
            this._override(Object.getPrototypeOf(kbd._aspectContainer), 'setRatio', clawSetRatio);
            kbd._aspectContainer._ratio = 10;
            kbd._aspectContainer.queue_relayout();

            // Keys are rebuilt into a fresh layout on every purpose/group change, even while the OSK is open
            this._hookCapsKeys(kbd._currentLayout);
            kbd._aspectContainer.disconnectObject?.(this);
            kbd._aspectContainer.connectObject?.(
                'child-added', (_container, child) => this._hookCapsKeys(child), this);
        }

        if (KeyboardUI.Keyboard?.prototype?._relayout)
            kbd._relayout = KeyboardUI.Keyboard.prototype._relayout.bind(kbd);

        const suggestions = kbd._suggestions;
        if (suggestions) {
            suggestions.disconnectObject?.(this);
            const sync = () => this._syncSuggestionsVisibility(suggestions);

            for (const child of suggestions.get_children()) {
                child.disconnectObject?.(this);
                child.connectObject?.('notify::visible', sync, this);
            }

            suggestions.connectObject(
                'child-added', (_container, child) => {
                    child.connectObject?.('notify::visible', sync, this);
                    sync();
                },
                'child-removed', (_container, child) => {
                    child.disconnectObject?.(this);
                    sync();
                },
                this
            );
            sync();
        }
    }

    // Replace obj[name], remembering the original only the first time so disable() can restore it
    _override(obj, name, value) {
        if (!obj)
            return;
        this._overrides ??= [];
        if (!this._overrides.some(o => o.obj === obj && o.name === name)) {
            this._overrides.push({
                obj, name,
                hadOwn: Object.prototype.hasOwnProperty.call(obj, name),
                orig: obj[name],
            });
        }
        obj[name] = value;
    }

    _restoreOverrides() {
        for (const {obj, name, hadOwn, orig} of (this._overrides ?? []).reverse()) {
            try {
                if (hadOwn)
                    obj[name] = orig;
                else
                    delete obj[name];
            } catch (e) {
                console.error(`ClawControls: Failed to restore ${name}:`, e);
            }
        }
        this._overrides = [];
    }

    // Stock levelSwitch only caps-locks on a long-pressed Shift key, so the layout's dedicated
    // Caps key acted as a one-shot Shift. Make it toggle a real caps lock instead.
    _hookCapsKeys(layout) {
        this._capsKeys ??= new Set();
        for (const level of layout?.get_children?.() ?? []) {
            if (!Array.isArray(level.shiftKeys))
                continue;
            for (const key of level.get_children()) {
                // Shift keys swap to the caps icon while latched, so exclude them explicitly
                if (key._icon?.icon_name !== 'osk-caps-lock-symbolic' ||
                    level.shiftKeys.includes(key) || this._capsKeys.has(key))
                    continue;
                this._capsKeys.add(key);
                let wasLatched = false;
                key.connectObject(
                    'pressed', () => {
                        wasLatched = !!Main.keyboard?._keyboard?._latched;
                    },
                    'released', () => {
                        // Runs after the stock handler, which already switched level and cleared the latch
                        const kb = Main.keyboard?._keyboard;
                        if (!wasLatched && kb?._layers?.['shift'] &&
                            typeof kb._setActiveLevel === 'function' &&
                            typeof kb._setLatched === 'function') {
                            kb._setActiveLevel('shift');
                            kb._setLatched(true);
                        }
                    },
                    'destroy', () => this._capsKeys?.delete(key),
                    this);
            }
        }
    }

    _enhanceOSKSizeAndLayout() {
        try {
            const extPath = this.path;
            const layoutCandidatePaths = [
                `${extPath}/us-enhanced.json`,
                '/usr/share/gnome-shell/extensions/claw-controls@msi-claw/us-enhanced.json',
                `${GLib.get_home_dir()}/.local/share/gnome-shell/extensions/claw-controls@msi-claw/us-enhanced.json`,
            ];
            let enhancedLayoutPath = null;
            for (const p of layoutCandidatePaths) {
                if (GLib.file_test(p, GLib.FileTest.EXISTS)) {
                    enhancedLayoutPath = p;
                    break;
                }
            }

            if (enhancedLayoutPath && !this._origNewForUri) {
                const origNewForUri = Gio.File.new_for_uri;
                this._origNewForUri = origNewForUri;
                Gio.File.new_for_uri = function (uri) {
                    if (uri === 'resource:///org/gnome/shell/osk-layouts/us.json' ||
                        uri === 'resource:///org/gnome/shell/osk-layouts/us-extended.json') {
                        return Gio.File.new_for_path(enhancedLayoutPath);
                    }
                    return origNewForUri.call(this, uri);
                };
            }

            if (KeyboardUI.Keyboard?.prototype) {
                if (!this._origRelayout)
                    this._origRelayout = KeyboardUI.Keyboard.prototype._relayout;

                KeyboardUI.Keyboard.prototype._relayout = function () {
                    const monitor = Main.layoutManager.keyboardMonitor;
                    const [minHeight] = this.get_preferred_height(-1);
                    if (!monitor)
                        return;

                    this.width = monitor.width;
                    if (monitor.width > monitor.height)
                        this.height = Math.round(monitor.height * 0.38);
                    else
                        this.height = Math.round(monitor.height * 0.32);

                    this.height = Math.clamp(
                        this.height,
                        minHeight,
                        Math.round(monitor.height * 0.48)
                    );
                };
            }

            const kbd = Main.keyboard?._keyboard;
            if (kbd) {
                this._attachKeyboardInstanceHooks(kbd);
                if (kbd._updateKeys)
                    kbd._updateKeys();
                if (kbd._relayout)
                    kbd._relayout();
            }

            // Re-apply tighter height after monitor/refresh-rate changes & new keyboard instances
            Main.layoutManager?.connectObject?.(
                'monitors-changed',
                () => {
                    const liveKbd = Main.keyboard?._keyboard;
                    if (liveKbd) {
                        this._attachKeyboardInstanceHooks(liveKbd);
                        liveKbd._relayout?.();
                    }
                },
                this
            );

            Main.keyboard?.connectObject?.(
                'visibility-changed',
                () => {
                    const liveKbd = Main.keyboard?._keyboard;
                    if (liveKbd) {
                        this._attachKeyboardInstanceHooks(liveKbd);
                        if (Main.keyboard.visible)
                            liveKbd._relayout?.();
                    }
                },
                this
            );
        } catch (e) {
            console.error('ClawControls: Error enhancing OSK size/layout:', e);
        }
    }

    _fixTouchscreenAndOSK() {
        try {
            if (Main.uiGroup) {
                const children = Main.uiGroup.get_children();
                for (const child of children) {
                    const name = child.get_name ? child.get_name() : '';
                    const styleClass = child.get_style_class_name ? child.get_style_class_name() : '';
                    if ((styleClass && styleClass.includes('modal-dialog')) ||
                        (name && name.toLowerCase().includes('osk'))) {
                        if (child !== Main.layoutManager.keyboardBox &&
                            child !== Main.layoutManager.modalDialogGroup) {
                            child.reactive = false;
                            child.hide();
                            child.destroy();
                        }
                    }
                }
            }

            const kmProto = KeyboardUI.KeyboardManager?.prototype ??
                (Main.keyboard ? Object.getPrototypeOf(Main.keyboard) : null);
            if (kmProto) {
                this._override(kmProto, '_lastDeviceIsTouchscreen', clawLastDeviceIsTouchscreen);
                this._override(kmProto, 'maybeHandleEvent', clawMaybeHandleEvent);
                if (Main.keyboard)
                    this._override(Main.keyboard, 'maybeHandleEvent', clawMaybeHandleEvent.bind(Main.keyboard));
            }

            const ibusMgr = IBusManager.getIBusManager?.();
            if (ibusMgr) {
                if (ibusMgr._oskCompletion && ibusMgr._setEngine) {
                    ibusMgr._oskCompletion = false;
                    ibusMgr._setEngine(ibusMgr._preOskEngine || 'xkb:us::eng').catch(() => {});
                    delete ibusMgr._preOskEngine;
                }
                this._override(ibusMgr, 'setCompletionEnabled', async () => false);
            }

            const kc = Main.keyboard?._keyboard?._keyboardController;
            if (kc) {
                kc._oskCompletionEnabled = false;
                const kcProto = Object.getPrototypeOf(kc);
                this._override(kcProto, 'keyvalPress', clawKeyvalPress);
                this._override(kcProto, 'keyvalRelease', clawKeyvalRelease);
            }

            const a11ySettings = new Gio.Settings({
                schema_id: 'org.gnome.desktop.a11y.applications',
            });
            if (!a11ySettings.get_boolean('screen-keyboard-enabled')) {
                a11ySettings.set_boolean('screen-keyboard-enabled', true);
            }
            if (Main.keyboard?._syncEnabled) {
                Main.keyboard._syncEnabled();
            }
        } catch (e) {
            console.error('ClawControls: Error fixing touchscreen/OSK:', e);
        }
    }

    requestModeToggle() {
        try {
            const cmdFile = GLib.get_user_runtime_dir() + '/msi-claw-cmd';
            GLib.file_set_contents(cmdFile, 'toggle\n');
        } catch (e) {
            console.error('ClawControls: Failed to write mode toggle command:', e);
        }
    }

    ToggleOSK() {
        try {
            if (!Main.keyboard)
                return;
            if (!Main.keyboard._keyboard && Main.keyboard._syncEnabled)
                Main.keyboard._syncEnabled();

            if (Main.keyboard.visible) {
                Main.keyboard.close();
            } else {
                const monitor = Main.layoutManager.bottomIndex ?? Main.layoutManager.primaryIndex ?? 0;
                Main.keyboard.open(monitor);
            }
        } catch (e) {
            console.error('ClawControls ToggleOSK error:', e);
        }
    }

    OpenOSK() {
        try {
            if (!Main.keyboard)
                return;
            if (!Main.keyboard._keyboard && Main.keyboard._syncEnabled)
                Main.keyboard._syncEnabled();
            if (!Main.keyboard.visible) {
                const monitor = Main.layoutManager.bottomIndex ?? Main.layoutManager.primaryIndex ?? 0;
                Main.keyboard.open(monitor);
            }
        } catch (e) {
            console.error('ClawControls OpenOSK error:', e);
        }
    }

    CloseOSK() {
        try {
            if (Main.keyboard?.visible)
                Main.keyboard.close();
        } catch (e) {
            console.error('ClawControls CloseOSK error:', e);
        }
    }

    ToggleOverview() {
        try {
            if (Main.sessionMode.isGreeter || Main.sessionMode.isLocked)
                return;
            Main.overview.toggle();
        } catch (e) {
            console.error('ClawControls ToggleOverview error:', e);
        }
    }

    ShowApps() {
        try {
            if (Main.sessionMode.isGreeter || Main.sessionMode.isLocked)
                return;
            if (Main.overview.visible)
                Main.overview.hide();
            else
                Main.overview.showApps();
        } catch (e) {
            console.error('ClawControls ShowApps error:', e);
        }
    }

    ToggleQuickSettings() {
        try {
            if (typeof Main.panel.toggleQuickSettings === 'function')
                Main.panel.toggleQuickSettings();
            else
                Main.panel.statusArea.quickSettings?.menu.toggle();
        } catch (e) {
            console.error('ClawControls ToggleQuickSettings error:', e);
        }
    }

    ShowOSD(icon, label) {
        try {
            const gicon = Gio.Icon.new_for_string(icon || 'input-gaming-symbolic');
            Main.osdWindowManager.showAll(gicon, label);
        } catch (e) {
            console.error('ClawControls ShowOSD error:', e);
        }
    }

    SetControllerMode(mode) {
        try {
            this._controllerMode = mode || 'desktop';
            this._indicator?.updateMode(this._controllerMode);
        } catch (e) {
            console.error('ClawControls SetControllerMode error:', e);
        }
    }
}
