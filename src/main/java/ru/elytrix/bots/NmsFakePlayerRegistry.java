package ru.elytrix.bots;

import com.mojang.authlib.GameProfile;
import org.bukkit.Bukkit;
import org.bukkit.World;

import java.lang.reflect.*;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.util.*;

/** Paper 1.16.5 player-list registration with a complete in-memory network stub. */
final class NmsFakePlayerRegistry {
    private final List<Object> entities = new ArrayList<>();
    private final Set<UUID> uuids = new HashSet<>();
    private final Map<UUID,Object> byUuid = new HashMap<>();
    private List<Object> serverPlayers;

    @SuppressWarnings("unchecked")
    void register(String name, UUID uuid, World world) {
        try {
            String nms = "net.minecraft.server." + Bukkit.getServer().getClass().getPackage().getName().split("\\.")[3] + ".";
            Object server = Bukkit.getServer().getClass().getMethod("getServer").invoke(Bukkit.getServer());
            Object worldServer = world.getClass().getMethod("getHandle").invoke(world);
            Class<?> mc = Class.forName(nms+"MinecraftServer"), ws=Class.forName(nms+"WorldServer");
            Class<?> interact=Class.forName(nms+"PlayerInteractManager"), entityPlayer=Class.forName(nms+"EntityPlayer");
            Object manager=interact.getConstructor(ws).newInstance(worldServer);
            Object entity=entityPlayer.getConstructor(mc,ws,GameProfile.class,interact).newInstance(server,worldServer,new GameProfile(uuid,name),manager);

            Class<?> direction=Class.forName(nms+"EnumProtocolDirection"), networkType=Class.forName(nms+"NetworkManager");
            Object clientbound=Arrays.stream(direction.getEnumConstants()).filter(v->v.toString().equals("CLIENTBOUND")).findFirst().orElseThrow();
            Object network=networkType.getConstructor(direction).newInstance(clientbound);
            prepareNetwork(network);
            Class<?> connectionType=Class.forName(nms+"PlayerConnection");
            Object connection=connectionType.getConstructor(mc,networkType,entityPlayer).newInstance(server,network,entity);
            entityPlayer.getField("playerConnection").set(entity,connection);

            if(serverPlayers==null){
                Object list=mc.getMethod("getPlayerList").invoke(server);
                Field field=list.getClass().getSuperclass().getDeclaredField("players"); field.setAccessible(true);
                serverPlayers=(List<Object>)field.get(list);
            }
            serverPlayers.add(entity); entities.add(entity); uuids.add(uuid); byUuid.put(uuid,entity);
        } catch (ReflectiveOperationException ex) { throw new IllegalStateException("Paper 1.16.5 fake player registration failed",ex); }
    }

    private void prepareNetwork(Object network) throws ReflectiveOperationException {
        // Essentials/TAB access address and plugins may send packets. A null channel caused their async NPEs.
        Object channel=Class.forName("io.netty.channel.embedded.EmbeddedChannel").getConstructor().newInstance();
        for(Class<?> type=network.getClass();type!=null;type=type.getSuperclass()) for(Field field:type.getDeclaredFields()) {
            field.setAccessible(true);
            if (Class.forName("io.netty.channel.Channel").isAssignableFrom(field.getType())) field.set(network,channel);
            else if (SocketAddress.class.isAssignableFrom(field.getType())) field.set(network,new InetSocketAddress("127.0.0.1",0));
        }
    }

    boolean isFake(UUID uuid){return uuids.contains(uuid);}
    org.bukkit.entity.Player player(UUID uuid){Object entity=byUuid.get(uuid);if(entity==null)return null;try{return (org.bukkit.entity.Player)entity.getClass().getMethod("getBukkitEntity").invoke(entity);}catch(Exception ignored){return null;}}
    int size(){return entities.size();}
    void remove(UUID uuid){Object entity=byUuid.remove(uuid);if(entity!=null){if(serverPlayers!=null)serverPlayers.remove(entity);entities.remove(entity);uuids.remove(uuid);}}
    void clear(){if(serverPlayers!=null)serverPlayers.removeAll(entities);entities.clear();uuids.clear();byUuid.clear();serverPlayers=null;}
}
