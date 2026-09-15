package ru.elytrix.efc.packet;

import com.github.retrooper.packetevents.event.PacketListenerAbstract;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.packettype.PacketType;
import com.github.retrooper.packetevents.protocol.packettype.PacketTypeCommon;
import com.github.retrooper.packetevents.protocol.world.Location;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientInteractEntity;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientInteractEntity.InteractAction;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientPlayerFlying;
import org.bukkit.entity.Player;
import ru.elytrix.efc.grim.GrimBridge;

/**
 * Слушатель входящих пакетов (API packetevents 2.x).
 * Только данные для проверок боя. Всё в try/catch.
 */
public final class PlayListener extends PacketListenerAbstract {

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
                if (use.getAction() == InteractAction.ATTACK) {
                    autoclickerHook(event);
                }
                GrimBridge.dispatchPacket(event);
            } else if (type == PacketType.Play.Client.ANIMATION) {
                Player player = event.getPlayer();
                if (player == null) {
                    return;
                }
                manager.swing(player);
            } else if (type == PacketType.Play.Client.CREATIVE_INVENTORY_ACTION
                    || type == PacketType.Play.Client.CLIENT_SETTINGS
                    || type == PacketType.Play.Client.CLICK_WINDOW
                    || type == PacketType.Play.Client.TAB_COMPLETE
                    || type == PacketType.Play.Client.ENTITY_ACTION
                    || type == PacketType.Play.Client.PONG
                    || type == PacketType.Play.Client.WINDOW_CONFIRMATION
                    || type == PacketType.Play.Client.ATTACK
                    || type == PacketType.Play.Client.SPECTATE_ENTITY) {
                GrimBridge.dispatchPacket(event);
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
        WrapperPlayClientPlayerFlying flying;
        try {
            flying = new WrapperPlayClientPlayerFlying(event);
        } catch (Throwable malformed) {
            event.setCancelled(true);
            return;
        }
        Location location = flying.getLocation();
        manager.flying(player, location.getX(), location.getY(), location.getZ(),
                location.getYaw(), location.getPitch(), flying.isOnGround(),
                flying.hasPositionChanged(), flying.hasRotationChanged());
        timerHook(event);
        GrimBridge.dispatchPacket(event);
    }

    private void timerHook(PacketReceiveEvent event) {
        try {
            ru.elytrix.efc.check.Check check = manager.getPlugin().getCheckManager().get("Timer.A");
            if (check instanceof ru.elytrix.efc.checks.movement.TimerA) {
                ((ru.elytrix.efc.checks.movement.TimerA) check).onPacketFlying(event);
            }
        } catch (Throwable ignored) {
        }
    }

    private void autoclickerHook(PacketReceiveEvent event) {
        try {
            ru.elytrix.efc.check.Check check = manager.getPlugin().getCheckManager().get("AutoClicker.A");
            if (check instanceof ru.elytrix.efc.checks.combat.AutoClickerA) {
                ((ru.elytrix.efc.checks.combat.AutoClickerA) check).onPacketAttack(event);
            }
        } catch (Throwable ignored) {
        }
    }
}
