# we store all generated files here.
# it must be pid-specific to allow for tests to run in parallel.
TMPDIR=tmp_bbxm_rtems_tester_directory.$$

IMG=$TMPDIR/bbxm_boot_sdcard.img
FATIMG=$TMPDIR/bbxm_boot_fat.img
SIZE=60000
OFFSET=2048
FATSIZE=`expr $SIZE - $OFFSET`
UENV=uEnv.txt

rm -rf $TMPDIR
mkdir -p $TMPDIR

if [ $# -ne 2 ]
then	echo "Usage: $0 <RTEMS tools bin dir> <RTEMS executable>"
	exit 1
fi

PREFIX=$1/../

if [ ! -d "$PREFIX" ]
then	echo "This script needs the RTEMS tools bindir as the first argument."
	exit 1
fi

QEMU=$PREFIX/qemu-linaro

if [ ! -d $QEMU ]
then	echo "This script needs the Linaro Qemu built, expected in $QEMU."
	echo "Is the bbxm.bset from the RTEMS source builder built?"
	exit 1
fi


executable=$2
app=rtems-app.img

if [ ! -f "$executable" ]
then	echo "Expecting RTEMS executable as arg; $executable not found."
	exit 1
fi

set -e

# Make an empty image
dd if=/dev/zero of=$IMG bs=512 seek=$SIZE count=1
dd if=/dev/zero of=$FATIMG bs=512 seek=`expr $FATSIZE - 1` count=1

# Make an ms-dos FS on it
$PREFIX/bin/newfs_msdos -r 1 -m 0xf8 -c 4 -F16  -h 64 -u 32 -S 512 -s $FATSIZE -o 0 ./$FATIMG

# Prepare the executable.
base=`basename $executable`
$PREFIX/bin/arm-rtems4.11-objcopy $executable -O binary $TMPDIR/$base.bin
gzip -9 $TMPDIR/$base.bin
$PREFIX/bin/mkimage -A arm -O rtems -T kernel -a 0x80000000 -e 0x80000000 -n RTEMS -d $TMPDIR/$base.bin.gz $TMPDIR/$app
echo "setenv bootdelay 5
uenvcmd=run boot
boot=fatload mmc 0 0x80800000 $app ; bootm 0x80800000" >$TMPDIR/$UENV

# Copy the uboot and app image onto the FAT image
$PREFIX/bin/mcopy -bsp -i $FATIMG $PREFIX/uboot/omap3_beagle/MLO ::MLO
$PREFIX/bin/mcopy -bsp -i $FATIMG $PREFIX/uboot/omap3_beagle/u-boot.img ::u-boot.img
$PREFIX/bin/mcopy -bsp -i $FATIMG $TMPDIR/$app ::$app
$PREFIX/bin/mcopy -bsp -i $FATIMG $TMPDIR/$UENV ::$UENV

# Just a single FAT partition (type C) that uses all of the image
$PREFIX/bin/partition -m $IMG $OFFSET 'c:0*+'

# Put the FAT image into the SD image
dd if=$FATIMG of=$IMG seek=$OFFSET

# Start qemu with the SD card image
set -x
#cp $executable /home/minix/bbxm/ # for gdb
$PREFIX/qemu-linaro/bin/qemu-system-arm -display none -serial stdio -M beaglexm -no-reboot -monitor none -nographic -sd $IMG || true

# cleanup
rm -rf $TMPDIR
