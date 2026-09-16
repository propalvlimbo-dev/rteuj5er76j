package ru.elytrix.bots;

import com.mojang.authlib.GameProfile;
import org.bukkit.Bukkit;
import org.bukkit.World;

import java.lang.reflect.*;
import java.util.*;

/** Paper 1.16.5-only lightweight registration, based on herby2212/FakePlayers' player-list approach. */
final class NmsFakePlayerRegistry {
    private final List<Object> registered = new ArrayList<>();
    private final Set<UUID> uuids = new HashSet<>();
    private List<Object> serverPlayers;

    @SuppressWarnings("unchecked")
    void register(String name, UUID uuid, World world) {
        try {
            String v = Bukkit.getServer().getClass().getPackage().getName().split("\\.")[3];
            String nms = "net.minecraft.server." + v + ".";
            Object minecraftServer = Bukkit.getServer().getClass().getMethod("getServer").invoke(Bukkit.getServer());
            Object worldServer = world.getClass().getMethod("getHandle").invoke(world);
            Class<?> mcClass = Class.forName(nms + "MinecraftServer");
            Class<?> wsClass = Class.forName(nms + "WorldServer");
            Class<?> managerClass = Class.forName(nms + "PlayerInteractManager");
            Class<?> entityClass = Class.forName(nms + "EntityPlayer");
            Object manager = managerClass.getConstructor(wsClass).newInstance(worldServer);
            Object entity = entityClass.getConstructor(mcClass, wsClass, GameProfile.class, managerClass)
                    .newInstance(minecraftServer, worldServer, new GameProfile(uuid, name), manager);

            Class<?> directionClass = Class.forName(nms + "EnumProtocolDirection");
            Object clientbound = Arrays.stream(directionClass.getEnumConstants()).filter(e -> e.toString().equals("CLIENTBOUND")).findFirst().orElseThrow();
            Class<?> networkClass = Class.forName(nms + "NetworkManager");
            Object network = networkClass.getConstructor(directionClass).newInstance(clientbound);
            Class<?> connectionClass = Class.forName(nms + "PlayerConnection");
            Object connection = connectionClass.getConstructor(mcClass, networkClass, entityClass).newInstance(minecraftServer, network, entity);
            Field connectionField = entityClass.getField("playerConnection"); connectionField.set(entity, connection);

            if (serverPlayers == null) {
                Object playerList = mcClass.getMethod("getPlayerList").invoke(minecraftServer);
                Field players = playerList.getClass().getSuperclass().getDeclaredField("players");
                players.setAccessible(true); serverPlayers = (List<Object>) players.get(playerList);
            }
            serverPlayers.add(entity); registered.add(entity); uuids.add(uuid);
        } catch (ReflectiveOperationException ex) {
            throw new IllegalStateException("NMS 1.16.5 registration failed", ex);
        }
    }

    int size() { return registered.size(); }
    boolean isFake(UUID uuid) { return uuids.contains(uuid); }
    void clear() {
        if (serverPlayers != null) serverPlayers.removeAll(registered);
        registered.clear(); uuids.clear(); serverPlayers = null;
    }
}
