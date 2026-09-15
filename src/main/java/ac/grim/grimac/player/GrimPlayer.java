package ac.grim.grimac.player;

import ac.grim.grimac.utils.change.BlockHistory;
import com.github.retrooper.packetevents.protocol.attribute.Attribute;
import com.github.retrooper.packetevents.protocol.attribute.Attributes;
import com.github.retrooper.packetevents.protocol.entity.type.EntityType;
import com.github.retrooper.packetevents.protocol.entity.type.EntityTypes;
import com.github.retrooper.packetevents.protocol.player.ClientVersion;
import com.github.retrooper.packetevents.protocol.player.GameMode;
import com.github.retrooper.packetevents.protocol.potion.PotionType;
import com.github.retrooper.packetevents.protocol.potion.PotionTypes;
import com.github.retrooper.packetevents.protocol.world.states.type.StateType;
import org.bukkit.entity.Player;
import org.bukkit.potion.PotionEffectType;
import ru.elytrix.efc.grim.GrimBridge;

/**
 * EFC-совместимость: Grim GrimPlayer.
 * Синхронизируется из Bukkit-игрока и пакетных данных через GrimBridge.
 */
public class GrimPlayer {

    public Player bukkitPlayer;

    public double x;
    public double y;
    public double z;
    public float yaw;
    public float pitch;
    public float lastYaw;
    public float lastPitch;

    public int entityID;

    public float food = 20.0F;
    public boolean canFly;
    public boolean isSprinting;
    public GameMode gamemode = GameMode.SURVIVAL;

    public final CameraEntity cameraEntity = new CameraEntity();
    public final CompensatedEntities compensatedEntities = new CompensatedEntities(this);
    public final CompensatedWorld compensatedWorld = new CompensatedWorld(this);
    public final PacketStateData packetStateData = new PacketStateData();
    public final TrigHandler trigHandler = new TrigHandler();
    public final BlockHistory blockHistory = new BlockHistory();

    private final SetbackTeleportUtil setbackTeleportUtil = new SetbackTeleportUtil(this);

    private ClientVersion clientVersion = ClientVersion.V_1_16;
    private long pingMillis = 50;
    private boolean inVehicle;
    private EntityType vehicleType = EntityTypes.PLAYER;

    public GrimPlayer(Player bukkitPlayer) {
        this.bukkitPlayer = bukkitPlayer;
    }

    public ClientVersion getClientVersion() {
        return clientVersion;
    }

    public void setClientVersion(ClientVersion clientVersion) {
        this.clientVersion = clientVersion;
    }

    public long getPingMillis() {
        return pingMillis;
    }

    public void setPingMillis(long pingMillis) {
        this.pingMillis = Math.max(0, pingMillis);
    }

    public boolean inVehicle() {
        return inVehicle;
    }

    public void setInVehicle(boolean inVehicle) {
        this.inVehicle = inVehicle;
    }

    public EntityType getVehicleType() {
        return vehicleType;
    }

    public void setVehicleType(EntityType vehicleType) {
        this.vehicleType = vehicleType;
    }

    public double[] getPossibleEyeHeights() {
        return new double[]{1.62D};
    }

    public double getMovementThreshold() {
        return 0.03D;
    }

    public boolean canSkipTicks() {
        return false;
    }

    public boolean isTickingReliablyFor(int ticks) {
        return true;
    }

    public long getPlayerClockAtLeast() {
        return System.nanoTime() - pingMillis * 1000000L;
    }

    public void onPacketCancel() {
    }

    public SetbackTeleportUtil getSetbackTeleportUtil() {
        return setbackTeleportUtil;
    }

    public boolean canUseGameMasterBlocks() {
        try {
            return bukkitPlayer != null && bukkitPlayer.isOp();
        } catch (Throwable ignored) {
            return false;
        }
    }

    public final class CameraEntity {
        public boolean isSelf() {
            return gamemode != GameMode.SPECTATOR;
        }
    }

    public static final class PacketStateData {
        public boolean didLastMovementIncludePosition;
        public boolean lastPacketWasTeleport;
    }

    public static final class TrigHandler {
        public float sin(float value) {
            return (float) Math.sin(value);
        }

        public float cos(float value) {
            return (float) Math.cos(value);
        }
    }

    public static final class CompensatedEntities {
        public final SelfEntity self;

        public CompensatedEntities(GrimPlayer player) {
            this.self = new SelfEntity(player);
        }
    }

    public static final class SelfEntity {
        private final GrimPlayer player;

        public SelfEntity(GrimPlayer player) {
            this.player = player;
        }

        public double getAttributeValue(Attribute attribute) {
            if (attribute == Attributes.BLOCK_INTERACTION_RANGE) {
                return player.gamemode == GameMode.CREATIVE ? 5.0D : 4.5D;
            }
            return 0.0D;
        }

        public boolean hasPotionEffect(PotionType type) {
            try {
                if (player.bukkitPlayer == null) return false;
                if (type == PotionTypes.BLINDNESS) {
                    return player.bukkitPlayer.hasPotionEffect(PotionEffectType.BLINDNESS);
                }
            } catch (Throwable ignored) {
            }
            return false;
        }
    }

    public static final class CompensatedWorld {
        private final GrimPlayer player;

        public CompensatedWorld(GrimPlayer player) {
            this.player = player;
        }

        public StateType getBlockType(int x, int y, int z) {
            return GrimBridge.blockTypeAt(player.bukkitPlayer, x, y, z);
        }
    }

    public static final class SetbackTeleportUtil {
        private final GrimPlayer player;

        public SetbackTeleportUtil(GrimPlayer player) {
            this.player = player;
        }

        public void executeNonSimulatingSetback() {
            GrimBridge.requestSetback(player);
        }
    }
}
