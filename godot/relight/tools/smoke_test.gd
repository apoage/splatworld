extends SceneTree
# M0 data gate (headless). Validates that GDGS imported the sample splat into a
# GaussianResource with a sane count / AABB / data buffers. Prints a checksum and
# exits nonzero on failure. Rendering is NOT validated here (headless = dummy
# driver); the visual check is a separate GPU run for human eyeballing.
#   godot --headless --path godot --script res://relight/tools/smoke_test.gd

# Defaults = the cactus sample; override for other assets via env:
#   SMOKE_ASSET=res://gs_assets/foo.ply  SMOKE_MIN_COUNT=50000  godot --headless ...
const DEFAULT_ASSET := "res://gs_assets/cactus_142k.ply"
const DEFAULT_MIN_COUNT := 100000     # cactus sample has 139410 splats

func _asset_path() -> String:
	var a := OS.get_environment("SMOKE_ASSET")
	return a if not a.is_empty() else DEFAULT_ASSET

func _min_count() -> int:
	var m := OS.get_environment("SMOKE_MIN_COUNT")
	return int(m) if m.is_valid_int() else DEFAULT_MIN_COUNT

func _initialize() -> void:
	var ok := true
	var asset := _asset_path()
	var min_count := _min_count()
	var res: Resource = load(asset)
	if res == null:
		push_error("[smoke] sample data missing — see data-release task (%s)" % asset)
		_finish(false)
		return

	var is_gs := res is GaussianResource
	var count: int = res.point_count if ("point_count" in res) else -1
	var xyz_len: int = res.xyz.size() if ("xyz" in res) else -1
	var fl: int = res.point_data_float.size() if ("point_data_float" in res) else -1
	var bl: int = res.point_data_byte.size() if ("point_data_byte" in res) else -1
	var aabb: AABB = res.aabb if ("aabb" in res) else AABB()

	print("[smoke] is GaussianResource: ", is_gs)
	print("[smoke] point_count=%d  xyz_len=%d  float_buf=%d  byte_buf=%d" % [count, xyz_len, fl, bl])
	print("[smoke] aabb pos=%s size=%s" % [aabb.position, aabb.size])

	# checksum: cheap, deterministic, would change if the buffer changed
	var checksum := 0.0
	if xyz_len > 0:
		checksum = res.xyz[0].length() + res.xyz[xyz_len / 2].length() + res.xyz[xyz_len - 1].length()
	print("[smoke] xyz_checksum=%f" % checksum)

	ok = ok and is_gs
	ok = ok and count > min_count         # default: cactus sample has 139410 splats
	ok = ok and xyz_len == count
	ok = ok and fl > 0
	ok = ok and _finite(aabb.position) and _finite(aabb.size) and aabb.size.length() > 0.0
	_finish(ok)

func _finite(v: Vector3) -> bool:
	return is_finite(v.x) and is_finite(v.y) and is_finite(v.z)

func _finish(ok: bool) -> void:
	print("SMOKE_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
