package ru.elytrix.efc.packet;

import io.github.retrooper.packetevents.PacketEvents;
import org.bukkit.entity.Player;

/**
 * Единственное место прямых касаний PacketEvents. Класс грузится лениво —
 * только когда плагин есть на сервере (PacketManager проверяет заранее).
 */
public final class PeHook {

    private PeHook() {
    }

    public static void register(PacketManager manager) {
        PacketEvents.get().getEventManager().registerListener(new PlayListener(manager));
    }

    public static int ping(Player player) {
        try {
            return PacketEvents.get().getPlayerUtils().getPing(player);
        } catch (Throwable ignored) {
            return -1;
        }
    }
}
