package ru.elytrix.efc.packet;

import com.github.retrooper.packetevents.event.PacketListenerAbstract;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.packettype.PacketType;
import com.github.retrooper.packetevents.protocol.packettype.PacketTypeCommon;
import com.github.retrooper.packetevents.protocol.world.Location;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientClickWindow;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientClickWindow.WindowClickType;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientInteractEntity;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientInteractEntity.InteractAction;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientNameItem;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientPlayerFlying;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientSettings;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientTabComplete;
import java.util.UUID;
import org.bukkit.entity.Player;

/**
 * Слушатель входящих пакетов (API packetevents 2.x).
 * Пишет данные для проверок + гасит краш-пакеты на месте (Grim Crash/Exploit).
 * Всё в try/catch — netty-поток умирать не должен. Флаги — из главного потока
 * через PacketManager.reportViolation.
 */
public final class PlayListener extends PacketListenerAbstract {

    private static final double HARD_BORDER = 2.9999999E7D;

    private final PacketManager manager;

    public PlayListener(PacketManager manager) {
        this.manager = manager;
    }

    @Override
    public void onPacketReceive(PacketReceiveEvent event) {
        try {
            PacketTypeCommon type = event.getPacketType();
            if (type == PacketType.Play.Client.PLAYER_FLYING
                    || type == PacketType.Play.Client.PLAYER_POSITION
                    || type == PacketType.Play.Client.PLAYER_ROTATION
                    || type == PacketType.Play.Client.PLAYER_POSITION_AND_ROTATION) {
                handleFlying(event);
            } else if (type == PacketType.Play.Client.INTERACT_ENTITY) {
                Player player = event.getPlayer();
                if (player == null) {
                    return;
                }
                WrapperPlayClientInteractEntity use = new WrapperPlayClientInteractEntity(event);
                if (use.getAction() == InteractAction.ATTACK) {
                    manager.attack(player, use.getEntityId());
                }
            } else if (type == PacketType.Play.Client.ANIMATION) {
                Player player = event.getPlayer();
                if (player == null) {
                    return;
                }
                manager.swing(player);
            } else if (type == PacketType.Play.Client.CREATIVE_INVENTORY_ACTION) {
                // Grim CrashB: клик креатива вне креатива (режим судит главный поток).
                event.setCancelled(true);
                report(event, "Crash.B", "creative-click");
            } else if (type == PacketType.Play.Client.CLIENT_SETTINGS) {
                handleSettings(event);
            } else if (type == PacketType.Play.Client.CLICK_WINDOW) {
                handleClickWindow(event);
            } else if (type == PacketType.Play.Client.TAB_COMPLETE) {
                handleTabComplete(event);
            } else if (type == PacketType.Play.Client.NAME_ITEM) {
                handleNameItem(event);
            }
        } catch (Throwable ignored) {
            // Пакетный слой никогда не роняет связь игрока.
        }
    }

    private void handleFlying(PacketReceiveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        UUID id = player.getUniqueId();
        WrapperPlayClientPlayerFlying flying;
        try {
            flying = new WrapperPlayClientPlayerFlying(event);
        } catch (Throwable malformed) {
            event.setCancelled(true);
            manager.reportViolation(id, "Crash.C", "malformed");
            return;
        }
        if (!flying.hasPositionChanged()) {
            Location location = flying.getLocation();
            manager.flying(player, location.getX(), location.getY(), location.getZ(),
                    location.getYaw(), location.getPitch(), flying.isOnGround(),
                    false, flying.hasRotationChanged());
            return;
        }
        Location location = flying.getLocation();
        double x = location.getX();
        double y = location.getY();
        double z = location.getZ();
        // Grim CrashC: нефинитные координаты/поворот.
        if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(z)
                || !Float.isFinite(location.getYaw()) || !Float.isFinite(location.getPitch())) {
            event.setCancelled(true);
            manager.reportViolation(id, "Crash.C", "nan");
            return;
        }
        // Grim CrashA: позиция за границей мира.
        if (Math.abs(x) > HARD_BORDER || Math.abs(z) > HARD_BORDER
                || Math.abs(y) > Integer.MAX_VALUE) {
            event.setCancelled(true);
            manager.reportViolation(id, "Crash.A", "oob");
            return;
        }
        manager.flying(player, x, y, z, location.getYaw(), location.getPitch(),
                flying.isOnGround(), true, flying.hasRotationChanged());
    }

    private void handleSettings(PacketReceiveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        try {
            WrapperPlayClientSettings settings = new WrapperPlayClientSettings(event);
            // Grim CrashE: дальность прорисовки ниже минимума.
            if (settings.getViewDistance() < 2) {
                settings.setViewDistance(2);
                manager.reportViolation(player.getUniqueId(), "Crash.E",
                        "vd=" + settings.getViewDistance());
            }
        } catch (Throwable malformed) {
            event.setCancelled(true);
            report(event, "Crash.E", "malformed");
        }
    }

    private void handleClickWindow(PacketReceiveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        UUID id = player.getUniqueId();
        WrapperPlayClientClickWindow click;
        try {
            click = new WrapperPlayClientClickWindow(event);
        } catch (Throwable malformed) {
            event.setCancelled(true);
            manager.reportViolation(id, "Crash.F", "malformed");
            return;
        }
        // Grim CrashF: невалидные кнопка/слот.
        WindowClickType clickType = click.getWindowClickType();
        int button = click.getButton();
        int windowId = click.getWindowId();
        int slot = click.getSlot();
        if ((clickType == WindowClickType.QUICK_MOVE || clickType == WindowClickType.SWAP)
                && windowId >= 0 && button < 0) {
            event.setCancelled(true);
            manager.reportViolation(id, "Crash.F", "button=" + button);
        } else if (windowId >= 0 && clickType == WindowClickType.SWAP && slot < 0) {
            event.setCancelled(true);
            manager.reportViolation(id, "Crash.F", "slot=" + slot);
        }
    }

    private void handleTabComplete(PacketReceiveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        try {
            String text = new WrapperPlayClientTabComplete(event).getText();
            if (text != null && text.length() > 64) {
                // Grim CrashH: длину и права судит главный поток.
                event.setCancelled(true);
                manager.reportViolation(player.getUniqueId(), "Crash.H", text);
            }
        } catch (Throwable malformed) {
            event.setCancelled(true);
            report(event, "Crash.H", "malformed");
        }
    }

    private void handleNameItem(PacketReceiveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        try {
            String name = new WrapperPlayClientNameItem(event).getItemName();
            // Grim ExploitA: имя в наковальне длиннее 50.
            if (name != null && name.length() > 50) {
                event.setCancelled(true);
                manager.reportViolation(player.getUniqueId(), "Exploit.A",
                        "len=" + name.length());
            }
        } catch (Throwable malformed) {
            event.setCancelled(true);
            report(event, "Exploit.A", "malformed");
        }
    }

    private void report(PacketReceiveEvent event, String checkId, String details) {
        try {
            Player player = event.getPlayer();
            if (player != null) {
                manager.reportViolation(player.getUniqueId(), checkId, details);
            }
        } catch (Throwable ignored) {
        }
    }
}
